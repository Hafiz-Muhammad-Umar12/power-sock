"""
Mapper module — Claude Vision-based UI element mapping.

Takes an ObservationResult and calls the Anthropic API with a vision-capable
Claude model to identify interactive UI elements and their semantic intent.
Returns validated MCPToolCandidate objects.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any

import anthropic
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
MAX_RETRIES = 1
INITIAL_BACKOFF_S = 2.0
MAX_BACKOFF_S = 30.0
DEFAULT_MODEL = "claude-sonnet-4-20250514"


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

Respond ONLY with a JSON array of tool candidates. No markdown, no explanation."""

MAPPER_USER_TEMPLATE = """\
Analyze this UI screenshot and accessibility tree from {url} (page title: "{title}").

The accessibility tree describes the DOM structure. Use both the screenshot and \
the tree to identify interactive elements.

Return a JSON array of MCP tool candidates."""


# ── Core mapper ──────────────────────────────────────────────────────────────


def _build_user_content(
    screenshot_b64: str | None,
    accessibility_tree: dict,
    url: str,
    title: str,
) -> list[dict[str, Any]]:
    """Build the multimodal content array for the Anthropic API."""
    content: list[dict[str, Any]] = []

    # Add the text prompt
    user_text = MAPPER_USER_TEMPLATE.format(url=url, title=title or "Untitled")
    content.append({"type": "text", "text": user_text})

    # Add the screenshot as an image
    if screenshot_b64:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": screenshot_b64,
            },
        })

    # Add the accessibility tree as text context
    a11y_text = json.dumps(accessibility_tree, indent=2, ensure_ascii=False)
    # Truncate if excessively long (Anthropic has context limits)
    max_a11y_chars = 50_000
    if len(a11y_text) > max_a11y_chars:
        a11y_text = a11y_text[:max_a11y_chars] + "\n... (truncated)"
    content.append({
        "type": "text",
        "text": f"\n\nAccessibility tree:\n```json\n{a11y_text}\n```",
    })

    return content


def _parse_candidates(raw_text: str) -> list[dict]:
    """Parse Claude's response text into a list of candidate dicts."""
    text = raw_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise VisionMappingError(
            f"Expected JSON array, got {type(parsed).__name__}"
        )
    return parsed


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


async def map_elements(
    screenshot_b64: str | None,
    accessibility_tree: dict,
    url: str = "",
    title: str = "",
    model: str = DEFAULT_MODEL,
) -> list[MCPToolCandidate]:
    """
    Send screenshot + accessibility tree to Claude Vision for semantic
    element mapping.

    Returns a list of validated MCPToolCandidate objects.
    Retries once on validation failure.
    Raises ClaudeAPIError, SchemaValidationError, or VisionMappingError.
    """
    if not settings.anthropic_api_key:
        raise ClaudeAPIError(None, "ANTHROPIC_API_KEY is not configured")

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    user_content = _build_user_content(screenshot_b64, accessibility_tree, url, title)

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            logger.info(
                "Calling Claude Vision (attempt %d/%d) for %s",
                attempt + 1,
                MAX_RETRIES + 1,
                url,
            )

            response = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=MAPPER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )

            # Extract text response
            raw_text = ""
            for block in response.content:
                if block.type == "text":
                    raw_text += block.text

            if not raw_text:
                raise VisionMappingError("Claude returned an empty response")

            # Parse and validate
            raw_candidates = _parse_candidates(raw_text)
            candidates = _validate_candidates(raw_candidates)

            logger.info(
                "Mapped %d elements from %s (attempt %d)",
                len(candidates),
                url,
                attempt + 1,
            )
            return candidates

        except (SchemaValidationError, VisionMappingError, json.JSONDecodeError) as e:
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

        except anthropic.RateLimitError as e:
            # Extract retry-after from headers if available
            retry_after = None
            if hasattr(e.response, "headers"):
                retry_after = float(e.response.headers.get("retry-after", INITIAL_BACKOFF_S))
            raise ClaudeRateLimitError(retry_after=retry_after) from e

        except anthropic.APIStatusError as e:
            raise ClaudeAPIError(e.status_code, str(e)) from e

        except anthropic.APIError as e:
            raise ClaudeAPIError(None, str(e)) from e

    # Should not reach here, but safety net
    raise last_error or VisionMappingError("Mapper failed after all retries")
