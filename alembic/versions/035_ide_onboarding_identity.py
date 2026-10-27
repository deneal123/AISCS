"""Server-owned starter identity; never evidence that a sandbox is pristine.

Revision ID: 035_ide_onboarding_identity
Revises: 034_ide_checkpoint_revisions
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "035_ide_onboarding_identity"
down_revision = "034_ide_checkpoint_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ide_repository",
        sa.Column("onboarding_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="profile",
    )
    op.create_index(
        "uq_ide_repository_onboarding",
        "ide_repository",
        ["user_id", "thread_id"],
        unique=True,
        schema="profile",
        postgresql_where=sa.text("onboarding_created"),
    )


def downgrade() -> None:
    op.drop_index("uq_ide_repository_onboarding", table_name="ide_repository", schema="profile")
    op.drop_column("ide_repository", "onboarding_created", schema="profile")
