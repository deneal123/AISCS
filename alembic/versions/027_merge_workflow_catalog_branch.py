"""Merge the autonomous workflow-catalog branch into the active migration head.

Revision ID: 027_merge_workflow_catalog_branch
Revises: 026_drop_implicit_routerai_image_prices, 010_workflow_catalog_outbox_leases
Create Date: 2026-08-26 16:00:00.000000
"""

from collections.abc import Sequence

revision: str = "027_merge_workflow_catalog_branch"
down_revision: str | Sequence[str] | None = (
    "026_drop_implicit_routerai_image_prices",
    "010_workflow_catalog_outbox_leases",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge-only revision; both predecessor branches already apply their DDL."""


def downgrade() -> None:
    """Merge-only revision; downgrade follows the selected predecessor branch."""
