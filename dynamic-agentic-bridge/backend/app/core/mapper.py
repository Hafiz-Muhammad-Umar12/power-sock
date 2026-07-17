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
import json
import logging
from typing import Any

import httpx
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
MAX_RETRIES = 2  # Local model may need more retries
INITIAL_BACKOFF_S = 1.0
MAX_BACKOFF_S = 10.0
DEFAULT_MODEL = "moondream"

# Timeout for Ollama API calls (local, but inference can be slow)
OLLAMA_TIMEOUT_S = 120


# ── System prompt ────────────────────────────────────────────────────────────

MAPPER_SYSTEM_PROMPT = """\
You are a UI analysis expert. Your task is to identify interactive UI elements \
from a screenshot and accessibility tree of a legacy web application, and map \
each element to a structured tool definition that an AI agent could call.

For each interactive element you identify, provide:
- element_type: The HTML element type (button, input, select, link, form, table, etc.)
- semantic_intent: A clear description of what this element does \
(e.g. "submit purchase order", "filter results by date range", "navigate to reports page")
- bounding_box: Approximate position {x, y, width, height} as percentages of viewport
- suggested_tool_schema: A JSON Schema object describing the input parameters \
this tool would accept (empty object {} if no parameters needed)
- requires_human_approval: true if this element performs a destructive action, \
submits data, spends money, or modifies external state; false for read-only \
navigation, filtering, or viewing actions

Focus on genuinely interactive elements: buttons, links, form inputs, dropdowns, \
tables with action columns, and navigation elements. Ignore purely decorative \
elements, static text, and layout containers.

IMPORTANT: You MUST respond with ONLY a valid JSON array of tool candidate objects. \
No markdown, no explanation, no text before or after the JSON. \
Example format: [{"element_type": "button", "semantic_intent": "...", \
"suggested_tool_schema": {}, "requires_human_approval": false}]"""

MAPPER_USER_TEMPLATE = """\
Analyze this UI screenshot and accessibility tree from {url} (page title: "{title}").

The accessibility tree describes the DOM structure. Use both the screenshot and \
the tree to identify interactive elements.

Return ALL MCP tool candidates you find as a JSON array."""


# ── Core mapper ──────────────────────────────────────────────────────────────


def _build_ollama_messages(
    screenshot_b64: str | None,
    accessibility_tree: dict,
    url: str,
    title: str,
) -> list[dict[str, Any]]:
    """Build the messages array for the Ollama chat API."""
    user_text = MAPPER_USER_TEMPLATE.format(url=url, title=title or "Untitled")

    # Add accessibility tree context
    a11y_text = json.dumps(accessibility_tree, indent=2, ensure_ascii=False)
    max_a11y_chars = 30_000  # Smaller limit for local models
    if len(a11y_text) > max_a11y_chars:
        a11y_text = a11y_text[:max_a11y_chars] + "\n... (truncated)"
    user_text += f"\n\nAccessibility tree:\n```json\n{a11y_text}\n```"

    message: dict[str, Any] = {"role": "user", "content": user_text}

    # Add screenshot as base64 image (Ollama's image format)
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

    # Ensure element_type is a string
    if "element_type" in result and not isinstance(result["element_type"], str):
        result["element_type"] = str(result["element_type"])

    # Ensure semantic_intent is a string
    if "semantic_intent" in result and not isinstance(result["semantic_intent"], str):
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

    Handles various shapes from different models:
    - JSON array of candidates (ideal)
    - Single candidate dict (moondream) → wraps in list
    - Dict with a key containing a list ({"candidates": [...]}) → unwraps
    - Dict with any key whose value is a list → unwraps
    """
    text = raw_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    parsed = json.loads(text)

    # Case 1: already a list — ideal
    if isinstance(parsed, list):
        return [_coerce_candidate(c) for c in parsed if isinstance(c, dict)]

    # Case 2: single dict that looks like a candidate → wrap in list
    if isinstance(parsed, dict):
        candidate_keys = {"element_type", "semantic_intent", "type", "role", "name", "label"}
        if candidate_keys & set(parsed.keys()):
            return [_coerce_candidate(parsed)]

        # Case 3: dict with a key whose value is a list — unwrap
        for key, val in parsed.items():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return [_coerce_candidate(c) for c in val if isinstance(c, dict)]

    raise VisionMappingError(
        f"Expected JSON array or candidate object, got {type(parsed).__name__}"
    )


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
                    "temperature": 0.1,  # Low temp for structured output
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
