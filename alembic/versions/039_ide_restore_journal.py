"""Private restore claims, unpublished until an exact native receipt is verified.

Revision ID: 039_ide_restore_journal
Revises: 038_pdf_preparation
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "039_ide_restore_journal"
down_revision = "038_pdf_preparation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ide_restore_intent",
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restore_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active_checkpoint_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("base_allocation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("storage_namespace", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("repository_id", "restore_id"),
        # Keep the private allocation ledger after chat deletion. Authorization
        # still joins the current owner; later cleanup needs this frozen record.
        sa.ForeignKeyConstraint(
            ["repository_id", "active_checkpoint_id"],
            [
                "profile.ide_checkpoint_intent.repository_id",
                "profile.ide_checkpoint_intent.checkpoint_id",
            ],
            name="fk_ide_restore_checkpoint",
        ),
        sa.UniqueConstraint("allocation_id", name="uq_ide_restore_allocation"),
        sa.CheckConstraint("allocation_id <> base_allocation_id", name="ck_ide_restore_fresh"),
        # Only an in-flight restore pins storage history. Terminal tombstones
        # retain replay identity without preventing future bounded retention.
        sa.CheckConstraint(
            "(state='pending') = (active_checkpoint_id IS NOT NULL) AND "
            "(active_checkpoint_id IS NULL OR active_checkpoint_id=checkpoint_id)",
            name="ck_ide_restore_pin",
        ),
        sa.CheckConstraint("expires_at > 0", name="ck_ide_restore_expiry"),
        sa.CheckConstraint("size > 0 AND size < 2147483648", name="ck_ide_restore_size"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_ide_restore_digest"),
        sa.CheckConstraint("storage_namespace ~ '^[0-9a-f]{64}$'", name="ck_ide_restore_storage"),
        sa.CheckConstraint(
            "state IN ('pending','published','expired','conflict')", name="ck_ide_restore_state"
        ),
        schema="profile",
    )
    op.create_index(
        "uq_ide_restore_active",
        "ide_restore_intent",
        ["repository_id"],
        unique=True,
        postgresql_where=sa.text("state='pending'"),
        schema="profile",
    )


def downgrade() -> None:
    op.drop_index("uq_ide_restore_active", table_name="ide_restore_intent", schema="profile")
    op.drop_table("ide_restore_intent", schema="profile")
