"""
SQLAlchemy 2.0 async ORM models for the Dynamic Agentic Bridge.
Target: PostgreSQL (NeonDB-compatible).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid4() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


# ── legacy_applications ─────────────────────────────────────────────────────


class LegacyApplication(Base):
    __tablename__ = "legacy_applications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    auth_credentials: Mapped[bytes | None] = mapped_column(
        Text, nullable=True  # Encrypted JSON, stored as text
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # Relationships
    state_nodes: Mapped[list[UIStateNode]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    execution_logs: Mapped[list[AgentExecutionLog]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<LegacyApplication {self.name}>"


# ── ui_state_nodes ──────────────────────────────────────────────────────────


class UIStateNode(Base):
    __tablename__ = "ui_state_nodes"
    __table_args__ = (
        Index("ix_ui_state_nodes_state_hash", "state_hash", unique=True),
        Index("ix_ui_state_nodes_app_id", "app_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid4
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("legacy_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    url_path: Mapped[str] = mapped_column(Text, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    screenshot_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    dom_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # Relationships
    application: Mapped[LegacyApplication] = relationship(back_populates="state_nodes")
    mapped_tools: Mapped[list[MappedMCPTool]] = relationship(
        back_populates="state_node", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<UIStateNode {self.state_hash[:12]}>"


# ── mapped_mcp_tools ────────────────────────────────────────────────────────


class MappedMCPTool(Base):
    __tablename__ = "mapped_mcp_tools"
    __table_args__ = (
        Index("ix_mapped_mcp_tools_state_node_id", "state_node_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid4
    )
    state_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ui_state_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    element_type: Mapped[str] = mapped_column(String(100), nullable=False)
    semantic_intent: Mapped[str] = mapped_column(Text, nullable=False)
    bounding_box: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mcp_tool_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    requires_human_approval: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # Relationships
    state_node: Mapped[UIStateNode] = relationship(back_populates="mapped_tools")
    execution_logs: Mapped[list[AgentExecutionLog]] = relationship(
        back_populates="tool"
    )

    def __repr__(self) -> str:
        return f"<MappedMCPTool {self.semantic_intent[:40]}>"


# ── agent_execution_logs ────────────────────────────────────────────────────


class AgentExecutionLog(Base):
    __tablename__ = "agent_execution_logs"
    __table_args__ = (
        Index("ix_agent_execution_logs_session_id", "session_id"),
        Index("ix_agent_execution_logs_execution_status", "execution_status"),
        CheckConstraint(
            "execution_status IN ('pending','success','failed','awaiting_human')",
            name="ck_execution_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("legacy_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mapped_mcp_tools.id", ondelete="SET NULL"),
        nullable=True,
    )
    action_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    execution_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_after_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # Relationships
    application: Mapped[LegacyApplication] = relationship(back_populates="execution_logs")
    tool: Mapped[MappedMCPTool | None] = relationship(back_populates="execution_logs")

    def __repr__(self) -> str:
        return f"<AgentExecutionLog {self.execution_status}>"
