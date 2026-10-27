"""Bounded scanning of settled, uncollected object ledger rows.

Revision ID: 042_ide_checkpoint_orphan_cleanup
Revises: 041_human_questions
"""

import sqlalchemy as sa

from alembic import op

revision = "042_ide_checkpoint_orphan_cleanup"
down_revision = "041_human_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_ide_cp_settled_cleanup",
        "ide_checkpoint_intent",
        ["storage_namespace", "repository_id", "checkpoint_id"],
        schema="profile",
        postgresql_where=sa.text("upload_settled_at IS NOT NULL AND collected_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_ide_cp_settled_cleanup", table_name="ide_checkpoint_intent", schema="profile")
