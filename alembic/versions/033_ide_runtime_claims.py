"""One durable allocation dispatch per IDE repository generation.

Revision ID: 033_ide_runtime_claims
Revises: 032_ide_repositories
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "033_ide_runtime_claims"
down_revision = "032_ide_repositories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ide_repository_runtime",
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("observation", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("retry_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"], ["profile.ide_repository.repository_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("repository_id"),
        sa.UniqueConstraint("allocation_id", name="uq_ide_runtime_allocation"),
        sa.CheckConstraint("expires_at > 0 AND observation >= 0", name="ck_ide_runtime_bounds"),
        sa.CheckConstraint("NOT retry_allowed OR state='rejected'", name="ck_ide_runtime_retry"),
        sa.CheckConstraint(
            "state IN ('dispatching','ready','pending','unknown','unavailable','expired','rejected')",
            name="ck_ide_runtime_state",
        ),
        schema="profile",
    )


def downgrade() -> None:
    op.drop_table("ide_repository_runtime", schema="profile")
