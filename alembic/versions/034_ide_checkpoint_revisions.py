"""Owned checkpoint intents and atomic repository head, independent of tmpfs.

Revision ID: 034_ide_checkpoint_revisions
Revises: 033_ide_runtime_claims
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "034_ide_checkpoint_revisions"
down_revision = "033_ide_runtime_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ide_checkpoint_intent",
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_checkpoint_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_namespace", sa.String(64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("repository_id", "checkpoint_id"),
        # Deliberately no cascading repo/thread/user FK: this row is also the
        # private object ledger. Deleting a chat during an upload must not erase
        # the only reference needed for subsequent orphan/deletion cleanup.
        # Authorization always joins the still-existing owned descriptor.
        sa.CheckConstraint("size >= 0 AND size < 9223372036854775807", name="ck_ide_cp_size"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_ide_cp_digest"),
        sa.CheckConstraint("storage_namespace ~ '^[0-9a-f]{64}$'", name="ck_ide_cp_storage"),
        sa.CheckConstraint(
            "state IN ('pending','published','conflict','retired')", name="ck_ide_cp_state"
        ),
        sa.CheckConstraint(
            "(state='published') = (published_at IS NOT NULL)", name="ck_ide_cp_published"
        ),
        sa.CheckConstraint(
            "base_checkpoint_id IS NULL OR base_checkpoint_id <> checkpoint_id",
            name="ck_ide_cp_base",
        ),
        schema="profile",
    )
    op.create_index(
        "ix_ide_cp_owner_scope",
        "ide_checkpoint_intent",
        ["user_id", "thread_id", "repository_id", "created_at"],
        schema="profile",
    )
    op.create_index(
        "ix_ide_cp_reconcile",
        "ide_checkpoint_intent",
        ["state", "created_at"],
        schema="profile",
    )
    op.create_table(
        "ide_repository_head",
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("repository_id"),
        sa.ForeignKeyConstraint(
            ["repository_id"], ["profile.ide_repository.repository_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["repository_id", "checkpoint_id"],
            [
                "profile.ide_checkpoint_intent.repository_id",
                "profile.ide_checkpoint_intent.checkpoint_id",
            ],
            name="fk_ide_head_checkpoint",
        ),
        schema="profile",
    )


def downgrade() -> None:
    op.drop_table("ide_repository_head", schema="profile")
    op.drop_index("ix_ide_cp_reconcile", table_name="ide_checkpoint_intent", schema="profile")
    op.drop_index("ix_ide_cp_owner_scope", table_name="ide_checkpoint_intent", schema="profile")
    op.drop_table("ide_checkpoint_intent", schema="profile")
