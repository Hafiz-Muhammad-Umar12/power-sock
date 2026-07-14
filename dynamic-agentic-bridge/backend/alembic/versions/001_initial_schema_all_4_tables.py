"""initial schema — all 4 tables

Revision ID: 001
Revises:
Create Date: 2025-01-15

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── legacy_applications ──────────────────────────────────────────────
    op.create_table(
        "legacy_applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("base_url", sa.Text, nullable=False),
        sa.Column("auth_credentials", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── ui_state_nodes ───────────────────────────────────────────────────
    op.create_table(
        "ui_state_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "app_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("legacy_applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url_path", sa.Text, nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("screenshot_url", sa.Text, nullable=True),
        sa.Column("dom_snapshot", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ui_state_nodes_state_hash", "ui_state_nodes", ["state_hash"], unique=True)
    op.create_index("ix_ui_state_nodes_app_id", "ui_state_nodes", ["app_id"])

    # ── mapped_mcp_tools ─────────────────────────────────────────────────
    op.create_table(
        "mapped_mcp_tools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "state_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ui_state_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("element_type", sa.String(100), nullable=False),
        sa.Column("semantic_intent", sa.Text, nullable=False),
        sa.Column("bounding_box", postgresql.JSONB, nullable=True),
        sa.Column(
            "mcp_tool_schema", postgresql.JSONB, nullable=False, server_default="{}"
        ),
        sa.Column(
            "requires_human_approval", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_mapped_mcp_tools_state_node_id", "mapped_mcp_tools", ["state_node_id"]
    )

    # ── agent_execution_logs ─────────────────────────────────────────────
    op.create_table(
        "agent_execution_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "app_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("legacy_applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tool_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mapped_mcp_tools.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "action_payload", postgresql.JSONB, nullable=False, server_default="{}"
        ),
        sa.Column(
            "execution_status",
            sa.String(20),
            nullable=False,
            server_default="'pending'",
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("screenshot_after_action", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "execution_status IN ('pending','success','failed','awaiting_human')",
            name="ck_execution_status",
        ),
    )
    op.create_index("ix_agent_execution_logs_session_id", "agent_execution_logs", ["session_id"])
    op.create_index(
        "ix_agent_execution_logs_execution_status",
        "agent_execution_logs",
        ["execution_status"],
    )


def downgrade() -> None:
    op.drop_table("agent_execution_logs")
    op.drop_table("mapped_mcp_tools")
    op.drop_table("ui_state_nodes")
    op.drop_table("legacy_applications")
