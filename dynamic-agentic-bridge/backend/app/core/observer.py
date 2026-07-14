"""
Observer module — Playwright-based legacy UI observation.
Stub for Phase 1; full implementation in Phase 3.
"""

from __future__ import annotations

from pydantic import BaseModel


class ObservationResult(BaseModel):
    """Structured output from observing a legacy application UI."""
    accessibility_tree: dict
    screenshot_bytes: bytes | None = None
    normalized_dom: dict
    state_hash: str
    url: str


async def observe_application(base_url: str) -> ObservationResult:
    """
    Launch a headless browser, navigate to the legacy app, and capture
    its UI state. Implementation coming in Phase 3.
    """
    raise NotImplementedError("Observer will be implemented in Phase 3")
