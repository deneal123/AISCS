"""Add durable Document Forge publication jobs.

Revision ID: 029_document_publication_jobs
Revises: 028_user_file_upload_intent
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "029_document_publication_jobs"
down_revision = "028_user_file_upload_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_publication_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.String(length=128), nullable=False),
        sa.Column("build_id", sa.String(length=128), nullable=False),
        sa.Column("artifact_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("artifact_size", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=1000), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("billing_job_id", sa.String(length=128), nullable=True),
        sa.Column("assistant_message_id", sa.BigInteger(), nullable=True),
        sa.Column("user_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["profile.user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_file_id"], ["profile.user_file.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "build_id",
            "artifact_id",
            "role",
            name="uq_document_publication_identity",
        ),
        schema="profile",
    )
    op.create_index(
        "ix_document_publication_due",
        "document_publication_job",
        ["status", "next_attempt_at", "lease_expires_at"],
        schema="profile",
    )
    op.create_index(
        "ix_document_publication_thread",
        "document_publication_job",
        ["thread_id"],
        schema="profile",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_publication_thread", table_name="document_publication_job", schema="profile"
    )
    op.drop_index(
        "ix_document_publication_due", table_name="document_publication_job", schema="profile"
    )
    op.drop_table("document_publication_job", schema="profile")
