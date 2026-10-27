"""Bound command control receipts and indexed recovery in the existing journal.

Revision ID: 047_command_receipts
Revises: 046_ide_command_operations
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "047_command_receipts"
down_revision = "046_ide_command_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "harness_task",
        sa.Column("verification_recipes", postgresql.JSONB, nullable=False, server_default="{}"),
        schema="profile",
    )
    op.create_check_constraint(
        "ck_harness_command_body",
        "harness_operation",
        "command IS NULL OR (jsonb_typeof(command)='object' "
        "AND octet_length(command::text)<=524288 "
        "AND COALESCE(command->>'state'=command_state,false))",
        schema="profile",
    )
    op.create_index(
        "ix_harness_command_recovery",
        "harness_operation",
        ["updated_at"],
        schema="profile",
        postgresql_where=sa.text(
            "command_state IN ('preparing','ready','dispatching','running','stopping','unknown')"
        ),
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM profile.harness_operation "
        "WHERE command_state IN "
        "('preparing','ready','dispatching','running','stopping','unknown')) "
        "THEN RAISE EXCEPTION 'Unresolved IDE commands'; END IF; END $$"
    )
    op.drop_index("ix_harness_command_recovery", table_name="harness_operation", schema="profile")
    op.drop_constraint("ck_harness_command_body", "harness_operation", schema="profile")
    op.drop_column("harness_task", "verification_recipes", schema="profile")
