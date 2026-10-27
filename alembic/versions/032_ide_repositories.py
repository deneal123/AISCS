"""Persist IDE repository descriptors independently of ephemeral sandboxes.

Revision ID: 032_ide_repositories
Revises: 031_document_audit_attempts
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "032_ide_repositories"
down_revision = "031_document_audit_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ide_repository",
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creation_intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["profile.chat_threads.thread_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["profile.user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("repository_id"),
        sa.UniqueConstraint(
            "user_id", "thread_id", "creation_intent_id", name="uq_ide_repo_intent"
        ),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 120", name="ck_ide_repo_name_length"),
        schema="profile",
    )
    op.create_index(
        "ix_ide_repository_owner_thread",
        "ide_repository",
        ["user_id", "thread_id", "created_at", "repository_id"],
        schema="profile",
    )


def downgrade() -> None:
    op.drop_index("ix_ide_repository_owner_thread", table_name="ide_repository", schema="profile")
    op.drop_table("ide_repository", schema="profile")
