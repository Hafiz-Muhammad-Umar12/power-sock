"""
MCP Tool Generator — converts mapped UI elements into MCP tool definitions
and persists them to the database.

Takes MCPToolCandidate objects from the mapper and produces:
1. A proper MCP tool definition (name, description, JSON Schema)
2. Persisted ui_state_nodes and mapped_mcp_tools rows
"""

from __future__ import annotations

import re
import uuid
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import MCPGeneratorError, PersistenceError, ToolSchemaError
from app.models.orm import MappedMCPTool, UIStateNode
from app.models.schemas import MCPToolCandidate

logger = logging.getLogger(__name__)


# ── Tool name generation ─────────────────────────────────────────────────────


def _make_tool_name(semantic_intent: str, element_type: str) -> str:
    """
    Generate a valid MCP tool name from semantic intent and element type.

    Rules:
    - Lowercase, underscores only (no spaces, hyphens, or special chars)
    - Prefixed with element type for namespacing
    - Max 64 characters
    """
    # Clean the semantic intent
    name = semantic_intent.lower().strip()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("_")

    # Prefix with element type
    prefix = element_type.lower().strip()
    prefix = re.sub(r"[^a-z0-9]", "_", prefix).strip("_")

    full_name = f"{prefix}__{name}" if prefix else name

    # Truncate to 64 chars
    return full_name[:64].rstrip("_")


# ── MCP tool definition generation ──────────────────────────────────────────


def generate_mcp_tool_definition(candidate: MCPToolCandidate) -> dict:
    """
    Generate an MCP tool definition from a validated candidate.

    Returns a dict with:
    - name: str
    - description: str
    - inputSchema: JSON Schema dict
    """
    if not candidate.semantic_intent:
        raise ToolSchemaError("semantic_intent is required")

    name = _make_tool_name(candidate.semantic_intent, candidate.element_type)

    # Build description
    description = candidate.semantic_intent
    if candidate.element_type:
        description = f"[{candidate.element_type}] {description}"
    if candidate.requires_human_approval:
        description += " ⚠️ Requires human approval"

    # Build input schema from suggested_tool_schema, ensuring it's valid JSON Schema
    input_schema = candidate.suggested_tool_schema if candidate.suggested_tool_schema else {}
    if not isinstance(input_schema, dict):
        raise ToolSchemaError(f"inputSchema must be a dict, got {type(input_schema).__name__}")

    # Ensure basic JSON Schema structure
    if "type" not in input_schema:
        input_schema["type"] = "object"

    tool_def = {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
        "annotations": {
            "requires_human_approval": candidate.requires_human_approval,
            "element_type": candidate.element_type,
            "bounding_box": candidate.bounding_box,
        },
    }

    logger.debug("Generated MCP tool: %s", name)
    return tool_def


# ── Database persistence ─────────────────────────────────────────────────────


async def persist_observation(
    db: AsyncSession,
    app_id: uuid.UUID,
    observation_result: dict,
    candidates: list[MCPToolCandidate],
) -> tuple[UIStateNode, list[MappedMCPTool]]:
    """
    Persist a UI state node and its mapped MCP tools to the database.

    Args:
        db: Async SQLAlchemy session
        app_id: UUID of the legacy application
        observation_result: Dict with url, state_hash, normalized_dom, screenshot_url, etc.
        candidates: Validated MCPToolCandidates from the mapper

    Returns:
        Tuple of (UIStateNode, list[MappedMCPTool])
    """
    try:
        # Create the UI state node
        state_node = UIStateNode(
            id=uuid.uuid4(),
            app_id=app_id,
            url_path=observation_result.get("url", ""),
            state_hash=observation_result.get("state_hash", ""),
            screenshot_url=observation_result.get("screenshot_url"),
            dom_snapshot=observation_result.get("normalized_dom", {}),
            is_active=True,
        )
        db.add(state_node)
        await db.flush()  # Get the ID without committing

        # Create mapped MCP tools
        mapped_tools: list[MappedMCPTool] = []
        for candidate in candidates:
            tool_def = generate_mcp_tool_definition(candidate)

            mapped_tool = MappedMCPTool(
                id=uuid.uuid4(),
                state_node_id=state_node.id,
                element_type=candidate.element_type,
                semantic_intent=candidate.semantic_intent,
                bounding_box=candidate.bounding_box,
                mcp_tool_schema=tool_def,
                requires_human_approval=candidate.requires_human_approval,
            )
            db.add(mapped_tool)
            mapped_tools.append(mapped_tool)

        await db.flush()

        logger.info(
            "Persisted state_node %s with %d tools for app %s",
            state_node.id,
            len(mapped_tools),
            app_id,
        )
        return state_node, mapped_tools

    except PersistenceError:
        raise
    except Exception as e:
        raise PersistenceError(f"Failed to persist observation: {e}") from e


# ── Full pipeline orchestrator ──────────────────────────────────────────────


async def process_observation(
    db: AsyncSession,
    app_id: uuid.UUID,
    base_url: str,
    auth_credentials: dict | None = None,
    url_path: str = "/",
) -> dict:
    """
    End-to-end observation pipeline:
    1. Observe the legacy app (Playwright)
    2. Map elements via Claude Vision
    3. Generate MCP tool definitions
    4. Persist everything to the database

    Returns a summary dict with state_node_id, tool_count, and state_hash.
    """
    from app.core.observer import observe_application
    from app.core.mapper import map_elements

    # Step 1: Observe
    logger.info("Pipeline step 1/4: Observing %s%s", base_url, url_path)
    observation = await observe_application(
        base_url=base_url,
        auth_credentials=auth_credentials,
        url_path=url_path,
    )

    # Step 2: Map elements via Claude Vision
    logger.info("Pipeline step 2/4: Mapping elements via Claude Vision")
    candidates = await map_elements(
        screenshot_b64=observation.screenshot_b64,
        accessibility_tree=observation.accessibility_tree,
        url=observation.url,
        title=observation.title,
    )

    # Step 3: Generate MCP definitions
    logger.info("Pipeline step 3/4: Generating MCP tool definitions")
    # (generation happens inside persist_observation)

    # Step 4: Persist
    logger.info("Pipeline step 4/4: Persisting to database")
    observation_dict = {
        "url": observation.url,
        "state_hash": observation.state_hash,
        "normalized_dom": observation.normalized_dom,
        "screenshot_url": observation.screenshot_b64,  # Store b64 for now
    }
    state_node, mapped_tools = await persist_observation(
        db=db,
        app_id=app_id,
        observation_result=observation_dict,
        candidates=candidates,
    )

    return {
        "state_node_id": str(state_node.id),
        "state_hash": state_node.state_hash,
        "tool_count": len(mapped_tools),
        "url": observation.url,
        "title": observation.title,
    }
