"""Add durable idempotency identity to user file intake.

Revision ID: 028_user_file_upload_intent
Revises: 027_merge_workflow_catalog_branch
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "028_user_file_upload_intent"
down_revision = "027_merge_workflow_catalog_branch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_file",
        sa.Column("upload_intent_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="profile",
    )
    op.add_column(
        "user_file",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        schema="profile",
    )
    op.create_unique_constraint(
        "uq_user_file_user_upload_intent",
        "user_file",
        ["user_id", "upload_intent_id"],
        schema="profile",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_user_file_user_upload_intent",
        "user_file",
        schema="profile",
        type_="unique",
    )
    op.drop_column("user_file", "content_sha256", schema="profile")
    op.drop_column("user_file", "upload_intent_id", schema="profile")
