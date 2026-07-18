"""
Mapper module — Ollama local LLM-based UI element mapping.

Takes an ObservationResult and calls a local Ollama model (moondream by default)
with a screenshot and accessibility tree to identify interactive UI elements
and their semantic intent. Returns validated MCPToolCandidate objects.

Uses Ollama's format="json" for structured output, validated against Pydantic.

NOTE: moondream is a small/fast local model (~2B params). Mapping accuracy and
structured-output reliability will be noticeably lower than cloud providers like
GPT-4o or Claude. This is expected for local testing — not a bug.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from typing import Any

import httpx
from PIL import Image
from pydantic import ValidationError

from app.config import settings
from app.core.exceptions import (
    ClaudeAPIError,
    ClaudeRateLimitError,
    SchemaValidationError,
    VisionMappingError,
)
from app.models.schemas import MCPToolCandidate

logger = logging.getLogger(__name__)

# Retry config
MAX_RETRIES = 4  # Local model is inconsistent; give more chances
INITIAL_BACKOFF_S = 1.0
MAX_BACKOFF_S = 10.0
DEFAULT_MODEL = "moondream"

# Timeout for Ollama API calls (local model on CPU can be slow with images)
OLLAMA_TIMEOUT_S = 300


# ── System prompt ────────────────────────────────────────────────────────────

MAPPER_SYSTEM_PROMPT = """\
Look at the screenshot. Find buttons, links, and form fields.
Reply with a JSON array. Each item has: element_type, semantic_intent.
element_type is button, link, input, or select.
semantic_intent describes what the element does in 5 words or fewer.
Example: [{"element_type":"button","semantic_intent":"submit the form"},
{"element_type":"link","semantic_intent":"go to home page"}]
Reply ONLY with the JSON array, nothing else."""

MAPPER_USER_TEMPLATE = """\
This is a screenshot of {url} (title: "{title}").
List the interactive elements you see: buttons, links, inputs, selects.

Return ALL MCP tool candidates you find as a JSON array."""


# ── Core mapper ──────────────────────────────────────────────────────────────


def _flatten_a11y_tree(node: dict, depth: int = 0, max_depth: int = 5) -> str:
    """
    Flatten an accessibility tree into a compact text summary.
    Small models like moondream handle text lists better than nested JSON.
    """
    lines: list[str] = []
    role = node.get("role", "")
    name = node.get("name", "")
    if role and role not in ("none", "presentation", "RootWebArea"):
        indent = "  " * depth
        label = f"{role}: {name}" if name else role
        lines.append(f"{indent}- {label}")
    children = node.get("children", [])
    if children and depth < max_depth:
        for child in children:
            lines.extend(_flatten_a11y_tree(child, depth + (1 if role and role not in ("none", "RootWebArea") else 0), max_depth))
    return lines


# ~4 chars per token (conservative for English + JSON)
CHARS_PER_TOKEN = 4
# moondream hard limit: 2048 tokens. Reserve ~200 for system prompt + user template.
# Image occupies ~500-1500 tokens depending on size, but we can't predict exactly.
# Conservative: budget 800 tokens (~3200 chars) for the a11y text when image present,
# 1600 tokens (~6400 chars) when no image.
MAX_A11Y_CHARS_WITH_IMAGE = 3_200
MAX_A11Y_CHARS_TEXT_ONLY = 6_400


# Max dimension for screenshots sent to Ollama (moondream works best <512px)
OLLAMA_MAX_IMAGE_DIM = 512


def _resize_screenshot(screenshot_b64: str, max_dim: int = OLLAMA_MAX_IMAGE_DIM) -> str:
    """Resize a base64 PNG screenshot to fit within max_dim pixels."""
    img_bytes = base64.b64decode(screenshot_b64)
    img = Image.open(io.BytesIO(img_bytes))
    w, h = img.size
    if max(w, h) <= max_dim:
        return screenshot_b64
    ratio = max_dim / max(w, h)
    new_w, new_h = int(w * ratio), int(h * ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    resized = base64.b64encode(buf.getvalue()).decode("ascii")
    logger.info(
        "Resized screenshot %dx%d -> %dx%d (%d -> %d chars b64)",
        w, h, new_w, new_h, len(screenshot_b64), len(resized),
    )
    return resized


def _build_ollama_messages(
    screenshot_b64: str | None,
    accessibility_tree: dict,
    url: str,
    title: str,
) -> list[dict[str, Any]]:
    """Build the messages array for the Ollama chat API."""
    user_text = MAPPER_USER_TEMPLATE.format(url=url, title=title or "Untitled")

    # Only include a11y tree for text-only mode (no image).
    # Small vision models like moondream loop recursively when given
    # a11y text alongside an image — they echo the text back infinitely.
    if not screenshot_b64:
        flat_lines = _flatten_a11y_tree(accessibility_tree)
        a11y_text = "\n".join(flat_lines) if flat_lines else "(empty)"
        max_chars = MAX_A11Y_CHARS_TEXT_ONLY
        if len(a11y_text) > max_chars:
            a11y_text = a11y_text[:max_chars] + "..."
        user_text += f"\n\nAccessibility tree:\n{a11y_text}"

    message: dict[str, Any] = {"role": "user", "content": user_text}

    if screenshot_b64:
        message["images"] = [screenshot_b64]

    return [
        {"role": "system", "content": MAPPER_SYSTEM_PROMPT},
        message,
    ]


def _coerce_candidate(raw: dict) -> dict:
    """
    Coerce a single candidate dict to fix common issues from small local
    models (moondream etc.):
    - Missing element_type/semantic_intent → map from role/name
    - bounding_box: list [x,y,w,h] → dict {x,y,width,height}
    - requires_human_approval: string → bool
    - suggested_tool_schema: non-dict → empty dict
    """
    result = dict(raw)

    # Map alternative key names to our schema
    if "element_type" not in result:
        if "type" in result:
            result["element_type"] = result.pop("type")
        elif "role" in result:
            result["element_type"] = result.pop("role")

    if "semantic_intent" not in result:
        if "name" in result:
            result["semantic_intent"] = result.pop("name")
        elif "label" in result:
            result["semantic_intent"] = result.pop("label")
        elif "text" in result:
            result["semantic_intent"] = result.pop("text")

    # Ensure element_type is a string (default to "element" if missing)
    if "element_type" not in result:
        result["element_type"] = "element"
    elif not isinstance(result["element_type"], str):
        result["element_type"] = str(result["element_type"])

    # Ensure semantic_intent is a string (default to description if missing)
    if "semantic_intent" not in result:
        # Try to build from whatever keys exist
        for key in ("description", "text", "content", "label", "title"):
            if key in result and isinstance(result[key], str):
                result["semantic_intent"] = result.pop(key)
                break
        else:
            result["semantic_intent"] = "UI element"
    elif not isinstance(result["semantic_intent"], str):
        result["semantic_intent"] = str(result["semantic_intent"])

    # Fix bounding_box: list → dict
    bb = result.get("bounding_box")
    if isinstance(bb, list) and len(bb) >= 2:
        if len(bb) == 4:
            result["bounding_box"] = {
                "x": bb[0], "y": bb[1], "width": bb[2], "height": bb[3],
            }
        elif len(bb) == 2:
            result["bounding_box"] = {"x": bb[0], "y": bb[1], "width": 5, "height": 5}

    # Fix requires_human_approval: string → bool
    approval = result.get("requires_human_approval")
    if isinstance(approval, str):
        result["requires_human_approval"] = approval.lower() in ("true", "yes", "1")

    # Fix suggested_tool_schema: non-dict → empty dict
    schema = result.get("suggested_tool_schema")
    if not isinstance(schema, dict):
        result["suggested_tool_schema"] = {}

    return result


def _parse_candidates(raw_text: str) -> list[dict]:
    """Parse LLM response text into a list of candidate dicts.

    Handles various shapes from different models, including malformed output
    from small local models like moondream:
    - JSON array of candidates (ideal)
    - Single candidate dict → wraps in list
    - Truncated JSON → attempts repair
    - Dict with any key/value pairs → coerces to candidate
    """
    text = raw_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Try parsing as-is first
    parsed = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Attempt repair: truncate at last complete object boundary
        repaired = _attempt_json_repair(text)
        if repaired is not None:
            parsed = repaired

    if parsed is None:
        raise VisionMappingError(f"Could not parse JSON from response")

    # Case 1: already a list
    if isinstance(parsed, list):
        return [_coerce_candidate(c) for c in parsed if isinstance(c, dict)]

    # Case 2: single dict — treat as a candidate
    if isinstance(parsed, dict):
        if any(isinstance(v, str) for v in parsed.values()):
            return [_coerce_candidate(parsed)]
        for val in parsed.values():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return [_coerce_candidate(c) for c in val if isinstance(c, dict)]

    raise VisionMappingError(
        f"Expected JSON array or candidate object, got {type(parsed).__name__}"
    )


def _attempt_json_repair(text: str) -> list | dict | None:
    """
    Attempt to repair truncated/malformed JSON from small models.
    Common pattern: model runs out of tokens mid-object, leaving incomplete JSON.
    """
    # Strategy 1: find the last complete }, ] or } and truncate there
    for end_char in ("]}", "]", "}"):
        idx = text.rfind(end_char)
        if idx > 0:
            candidate = text[: idx + len(end_char)]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, (list, dict)):
                    logger.warning("Repaired truncated JSON by cutting at pos %d", idx)
                    return parsed
            except json.JSONDecodeError:
                continue

    # Strategy 2: try wrapping incomplete object in array brackets
    if text.startswith("{") and not text.startswith("["):
        # Find the last complete key-value pair
        last_brace = text.rfind("}")
        if last_brace > 0:
            candidate = text[: last_brace + 1] + "]"
            try:
                parsed = json.loads("[" + text[: last_brace + 1])
                if isinstance(parsed, list) and parsed:
                    logger.warning("Repaired incomplete object by wrapping in array")
                    return parsed
            except json.JSONDecodeError:
                pass

    return None


def _validate_candidates(raw_candidates: list[dict]) -> list[MCPToolCandidate]:
    """Validate raw candidate dicts against MCPToolCandidate schema."""
    validated: list[MCPToolCandidate] = []
    errors: list[dict] = []

    for i, raw in enumerate(raw_candidates):
        try:
            candidate = MCPToolCandidate.model_validate(raw)
            validated.append(candidate)
        except ValidationError as e:
            errors.append({"index": i, "errors": e.errors()})

    if errors and not validated:
        raise SchemaValidationError(errors)

    if errors:
        logger.warning(
            "Some candidates failed validation (%d/%d), proceeding with valid ones",
            len(errors),
            len(raw_candidates),
        )

    return validated


async def _call_ollama(
    messages: list[dict],
    model: str,
) -> str:
    """
    Call the Ollama chat API and return the response text.

    Uses format="json" to request structured JSON output.
    """
    base_url = settings.ollama_base_url.rstrip("/")

    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_S) as client:
        response = await client.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_ctx": 8192,
                },
            },
        )

    if response.status_code == 404:
        raise ClaudeAPIError(
            404,
            f"Model '{model}' not found. Pull it with: ollama pull {model}"
        )

    if response.status_code != 200:
        raise ClaudeAPIError(
            response.status_code,
            f"Ollama API error: {response.text[:500]}"
        )

    data = response.json()
    content = data.get("message", {}).get("content", "")

    logger.info("[MOONDREAM RAW] %s", content[:1500] if content else "<empty>")

    if not content:
        raise VisionMappingError("Ollama returned an empty response")

    return content


async def map_elements(
    screenshot_b64: str | None,
    accessibility_tree: dict,
    url: str = "",
    title: str = "",
    model: str = DEFAULT_MODEL,
) -> list[MCPToolCandidate]:
    """
    Send screenshot + accessibility tree to a local Ollama model for semantic
    element mapping.

    Uses Ollama's format="json" for structured output.
    Returns a list of validated MCPToolCandidate objects.
    Retries up to MAX_RETRIES times on validation/parse failure.

    NOTE: moondream is a small local model. Accuracy and structured output
    reliability will be lower than cloud providers — this is expected.
    """
    resolved_model = model or settings.ollama_model

    # Resize large screenshots — moondream on CPU can't handle multi-MB images
    if screenshot_b64:
        screenshot_b64 = _resize_screenshot(screenshot_b64)

    messages = _build_ollama_messages(screenshot_b64, accessibility_tree, url, title)

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            logger.info(
                "Calling Ollama %s (attempt %d/%d) for %s",
                resolved_model,
                attempt + 1,
                MAX_RETRIES + 1,
                url,
            )

            raw_text = await _call_ollama(messages, resolved_model)

            logger.info("[ATTEMPT %d] Raw: %s", attempt + 1, raw_text[:300])

            # Parse JSON response
            raw_candidates = _parse_candidates(raw_text)

            if not raw_candidates:
                raise VisionMappingError("Model returned no tool candidates")

            # Validate against Pydantic schema
            candidates = _validate_candidates(raw_candidates)

            logger.info(
                "Mapped %d elements from %s via Ollama (attempt %d)",
                len(candidates),
                url,
                attempt + 1,
            )
            return candidates

        except (SchemaValidationError, VisionMappingError, json.JSONDecodeError, KeyError) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                logger.warning(
                    "Validation/parse failed (attempt %d), retrying: %s",
                    attempt + 1,
                    e,
                )
                await asyncio.sleep(INITIAL_BACKOFF_S * (attempt + 1))
                continue
            raise

        except httpx.TimeoutException as e:
            raise ClaudeAPIError(None, f"Ollama request timed out: {e}") from e

        except httpx.HTTPError as e:
            raise ClaudeAPIError(None, f"Ollama connection error: {e}") from e

    # Should not reach here, but safety net
    raise last_error or VisionMappingError("Mapper failed after all retries")
