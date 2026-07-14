"""
Pydantic v2 models for request/response validation.
SQLAlchemy ORM models will be added in Phase 2.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ── Application ──────────────────────────────────────────────────────────────


class ApplicationCreate(BaseModel):
    name: str
    base_url: str
    auth_credentials: dict | None = None


class ApplicationResponse(BaseModel):
    id: UUID
    name: str
    base_url: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── MCP Tool ─────────────────────────────────────────────────────────────────


class MCPToolResponse(BaseModel):
    id: UUID
    state_node_id: UUID
    element_type: str
    semantic_intent: str
    bounding_box: dict | None = None
    mcp_tool_schema: dict
    requires_human_approval: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Execution ────────────────────────────────────────────────────────────────


class ExecutionCreate(BaseModel):
    tool_id: UUID
    action_payload: dict = Field(default_factory=dict)


class ExecutionResponse(BaseModel):
    id: UUID
    session_id: UUID
    app_id: UUID
    tool_id: UUID | None = None
    action_payload: dict
    execution_status: str
    error_message: str | None = None
    screenshot_after_action: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Observation ──────────────────────────────────────────────────────────────


class ObservationRequest(BaseModel):
    """Trigger an observation session for a legacy application."""
    pass  # No params needed — app_id comes from the URL path


class ObservationResponse(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    status: str = "queued"
    message: str = "Observation pipeline triggered"


# ── MCP Tool Candidate (internal) ───────────────────────────────────────────


class MCPToolCandidate(BaseModel):
    """Internal model for mapper output before persistence."""
    element_type: str
    semantic_intent: str
    bounding_box: dict | None = None
    suggested_tool_schema: dict = Field(default_factory=dict)
    requires_human_approval: bool = False


# ── Health ───────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
