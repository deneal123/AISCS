"""IDE commands extend the existing operation journal, not a parallel job queue.

Revision ID: 046_ide_command_operations
Revises: 045_harness_holds
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "046_ide_command_operations"
down_revision = "045_harness_holds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("command_repository_id", postgresql.UUID(as_uuid=True)),
        sa.Column("command_workspace_id", sa.String(128)),
        sa.Column("command_state", sa.String(16)),
        sa.Column("command", postgresql.JSONB),
    ):
        op.add_column("harness_operation", column, schema="profile")
    active = "command_state IN ('preparing','ready','dispatching','running','stopping','unknown')"
    for name, column in (
        ("ix_harness_command_repository", "command_repository_id"),
        ("ix_harness_command_workspace", "command_workspace_id"),
    ):
        op.create_index(name, "harness_operation", [column], schema="profile", unique=True,
                        postgresql_where=sa.text(active))
    op.create_check_constraint(
        "ck_harness_command_state", "harness_operation",
        "(command IS NULL AND command_state IS NULL AND command_repository_id IS NULL "
        "AND command_workspace_id IS NULL) OR (command IS NOT NULL "
        "AND command_repository_id IS NOT NULL AND command_workspace_id IS NOT NULL "
        "AND command_state IN ('preparing','ready','dispatching','running','stopping',"
        "'unknown','completed','failed','cancelled') AND command->>'state'=command_state)",
        schema="profile",
    )
    op.add_column("ide_checkpoint_intent", sa.Column("command_pins", sa.Integer, nullable=False,
                                                     server_default="0"), schema="profile")
    op.create_check_constraint("ck_checkpoint_command_pins", "ide_checkpoint_intent",
                               "command_pins>=0", schema="profile")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM profile.harness_operation "
               "WHERE command_state IN ('preparing','ready','dispatching','running','stopping',"
               "'unknown')) OR EXISTS(SELECT 1 FROM profile.ide_checkpoint_intent "
               "WHERE command_pins>0) THEN RAISE EXCEPTION 'Unresolved IDE commands'; END IF; END $$")
    op.drop_constraint("ck_checkpoint_command_pins", "ide_checkpoint_intent", schema="profile")
    op.drop_column("ide_checkpoint_intent", "command_pins", schema="profile")
    op.drop_constraint("ck_harness_command_state", "harness_operation", schema="profile")
    for name in ("ix_harness_command_repository", "ix_harness_command_workspace"):
        op.drop_index(name, table_name="harness_operation", schema="profile")
    for column in ("command", "command_state", "command_workspace_id", "command_repository_id"):
        op.drop_column("harness_operation", column, schema="profile")
