"""Durable first-entry PDF allocation intent; never store sandbox credentials.

Revision ID: 038_pdf_preparation
Revises: 037_ide_clone_recovery
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "038_pdf_preparation"
down_revision = "037_ide_clone_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pdf_preparation",
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workspace_id", sa.String(32), nullable=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("scaffold_state", sa.String(16), nullable=False, server_default="idle"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["profile.chat_threads.thread_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("thread_id"),
        sa.UniqueConstraint("allocation_id", name="uq_pdf_preparation_allocation"),
        sa.CheckConstraint("expires_at > 0", name="ck_pdf_preparation_expiry"),
        sa.CheckConstraint(
            "scaffold_state IN ('idle','dispatching','rejected','observed')",
            name="ck_pdf_preparation_scaffold",
        ),
        sa.CheckConstraint(
            "(allocation_id IS NOT NULL AND workspace_id IS NULL) OR "
            "(allocation_id IS NULL AND workspace_id IS NOT NULL)",
            name="ck_pdf_preparation_identity",
        ),
        schema="profile",
    )


def downgrade() -> None:
    op.drop_table("pdf_preparation", schema="profile")
