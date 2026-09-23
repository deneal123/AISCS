"""Lease and classify autonomous workflow catalog outbox delivery.

Revision ID: 010_workflow_catalog_outbox_leases
Revises: 009_autonomous_workflow_catalog
Create Date: 2026-08-26 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "010_workflow_catalog_outbox_leases"
down_revision: str | Sequence[str] | None = "009_autonomous_workflow_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_catalog_outbox",
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        schema="profile",
    )
    op.add_column(
        "workflow_catalog_outbox",
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        schema="profile",
    )
    op.add_column(
        "workflow_catalog_outbox",
        sa.Column("last_error_class", sa.String(64), nullable=True),
        schema="profile",
    )
    op.add_column(
        "workflow_catalog_outbox",
        sa.Column("lease_token", sa.UUID(), nullable=True),
        schema="profile",
    )
    op.create_index(
        "ix_workflow_catalog_outbox_lease",
        "workflow_catalog_outbox",
        ["delivered_at", "available_at", "lease_until"],
        schema="profile",
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_catalog_outbox_lease", table_name="workflow_catalog_outbox", schema="profile")
    op.drop_column("workflow_catalog_outbox", "last_error_class", schema="profile")
    op.drop_column("workflow_catalog_outbox", "lease_token", schema="profile")
    op.drop_column("workflow_catalog_outbox", "lease_until", schema="profile")
    op.drop_column("workflow_catalog_outbox", "leased_at", schema="profile")
