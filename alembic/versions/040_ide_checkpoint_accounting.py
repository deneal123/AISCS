"""Account for uncertain uploads until a settled writer and delete ACK exist.

Revision ID: 040_ide_checkpoint_accounting
Revises: 039_ide_restore_journal
"""

import sqlalchemy as sa

from alembic import op

revision = "040_ide_checkpoint_accounting"
down_revision = "039_ide_restore_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Do not manufacture settlement receipts for historical/unknown writers.
    op.add_column(
        "ide_checkpoint_intent",
        sa.Column("upload_settled_at", sa.DateTime(timezone=True), nullable=True),
        schema="profile",
    )
    op.add_column(
        "ide_checkpoint_intent",
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        schema="profile",
    )
    op.create_check_constraint(
        "ck_ide_cp_collected",
        "ide_checkpoint_intent",
        "collected_at IS NULL OR (state IN ('retired','conflict') "
        "AND upload_settled_at IS NOT NULL)",
        schema="profile",
    )
    op.create_index(
        "ix_ide_cp_uncollected_budget",
        "ide_checkpoint_intent",
        ["user_id"],
        schema="profile",
        postgresql_where=sa.text("collected_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ide_cp_uncollected_budget", table_name="ide_checkpoint_intent", schema="profile"
    )
    op.drop_constraint(
        "ck_ide_cp_collected", "ide_checkpoint_intent", type_="check", schema="profile"
    )
    op.drop_column("ide_checkpoint_intent", "collected_at", schema="profile")
    op.drop_column("ide_checkpoint_intent", "upload_settled_at", schema="profile")
