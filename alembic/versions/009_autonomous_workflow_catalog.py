# ruff: noqa: E501 - DDL declarations remain legible as one schema field per line.
"""Add the backend-owned autonomous workflow catalog.

Revision ID: 009_autonomous_workflow_catalog
Revises: 008_drop_legacy_tables
Create Date: 2026-08-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "009_autonomous_workflow_catalog"
down_revision: str | Sequence[str] | None = "008_drop_legacy_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_catalog",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False, unique=True),
        sa.Column("label_ru", sa.String(300), nullable=False),
        sa.Column("steps", JSONB, nullable=False),
        sa.Column("cost_class", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("state", sa.String(32), nullable=False, server_default="active"),
        sa.Column("quality_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("reuse_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("index_point_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="profile",
    )
    op.create_table(
        "workflow_catalog_examples",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("workflow_id", UUID(as_uuid=True), nullable=True),
        sa.Column("steps", JSONB, nullable=False),
        sa.Column("cost_class", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("thread_id", sa.String(128), nullable=False),
        sa.Column("request_text", sa.Text, nullable=False),
        sa.Column("succeeded", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["profile.workflow_catalog.id"], ondelete="SET NULL"),
        schema="profile",
    )
    op.create_index(
        "ix_workflow_catalog_examples_fingerprint_success",
        "workflow_catalog_examples",
        ["fingerprint", "succeeded", "created_at"],
        schema="profile",
    )
    op.create_index(
        "ix_workflow_catalog_examples_expires_at",
        "workflow_catalog_examples",
        ["expires_at"],
        schema="profile",
    )
    op.create_table(
        "workflow_catalog_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_version", sa.Integer, nullable=False),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("thread_id", sa.String(128), nullable=False),
        sa.Column("content_key", sa.String(128), nullable=False),
        sa.Column("succeeded", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["workflow_id"], ["profile.workflow_catalog.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workflow_id", "thread_id", "content_key", name="uq_workflow_catalog_execution"),
        schema="profile",
    )
    op.create_table(
        "workflow_catalog_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("execution_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("rating", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["profile.workflow_catalog_executions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("execution_id", "user_id", name="uq_workflow_catalog_feedback"),
        schema="profile",
    )
    op.create_table(
        "workflow_catalog_outbox",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", UUID(as_uuid=True), nullable=False),
        sa.Column("example_id", UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["workflow_id"], ["profile.workflow_catalog.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["example_id"], ["profile.workflow_catalog_examples.id"], ondelete="SET NULL"),
        schema="profile",
    )
    op.create_index(
        "ix_workflow_catalog_outbox_delivery",
        "workflow_catalog_outbox",
        ["delivered_at", "available_at"],
        schema="profile",
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_catalog_outbox_delivery", table_name="workflow_catalog_outbox", schema="profile")
    op.drop_table("workflow_catalog_outbox", schema="profile")
    op.drop_table("workflow_catalog_feedback", schema="profile")
    op.drop_table("workflow_catalog_executions", schema="profile")
    op.drop_index("ix_workflow_catalog_examples_expires_at", table_name="workflow_catalog_examples", schema="profile")
    op.drop_index(
        "ix_workflow_catalog_examples_fingerprint_success",
        table_name="workflow_catalog_examples",
        schema="profile",
    )
    op.drop_table("workflow_catalog_examples", schema="profile")
    op.drop_table("workflow_catalog", schema="profile")
