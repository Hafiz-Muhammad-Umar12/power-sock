"""
Mapper module — Claude Vision-based UI element mapping.
Stub for Phase 1; full implementation in Phase 3.
"""

from __future__ import annotations

from app.models.schemas import MCPToolCandidate


async def map_elements(
    accessibility_tree: dict,
    screenshot_bytes: bytes | None,
) -> list[MCPToolCandidate]:
    """
    Send screenshot + accessibility tree to Claude Vision for semantic
    element mapping. Implementation coming in Phase 3.
    """
    raise NotImplementedError("Mapper will be implemented in Phase 3")
