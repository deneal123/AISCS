"""Owned public clone parameters for recovery; never credentials or source bytes.

Revision ID: 037_ide_clone_recovery
Revises: 036_ide_clone_intents
"""

import sqlalchemy as sa

from alembic import op

revision = "037_ide_clone_recovery"
down_revision = "036_ide_clone_intents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ide_clone_intent", sa.Column("origin", sa.String(512)), schema="profile")
    op.add_column("ide_clone_intent", sa.Column("branch", sa.String(200)), schema="profile")
    op.create_index(
        "ix_ide_clone_recovery",
        "ide_clone_intent",
        ["user_id", "thread_id", "created_at", "intent_id"],
        schema="profile",
    )


def downgrade() -> None:
    op.drop_index("ix_ide_clone_recovery", table_name="ide_clone_intent", schema="profile")
    op.drop_column("ide_clone_intent", "branch", schema="profile")
    op.drop_column("ide_clone_intent", "origin", schema="profile")
