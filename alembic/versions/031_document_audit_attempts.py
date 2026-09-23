"""Add durable Document Forge visual-audit attempts.

Revision ID: 031_document_audit_attempts
Revises: 030_document_pub_repair
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "031_document_audit_attempts"
down_revision = "030_document_pub_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_audit_attempt",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publication_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("build_id", sa.String(length=128), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("usage_envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reservation_id", sa.String(length=128), nullable=True),
        sa.Column("charge_id", sa.String(length=128), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["publication_job_id"],
            ["profile.document_publication_job.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["profile.user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="profile",
    )
    op.create_index(
        "uq_document_audit_attempt_open",
        "document_audit_attempt",
        ["publication_job_id"],
        unique=True,
        schema="profile",
        postgresql_where=sa.text("state IN ('started','charge_pending')"),
    )
    op.create_index(
        "ix_document_audit_attempt_unsettled",
        "document_audit_attempt",
        ["publication_job_id", "state", "created_at"],
        schema="profile",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_document_audit_attempt_open",
        table_name="document_audit_attempt",
        schema="profile",
    )
    op.drop_index(
        "ix_document_audit_attempt_unsettled",
        table_name="document_audit_attempt",
        schema="profile",
    )
    op.drop_table("document_audit_attempt", schema="profile")
