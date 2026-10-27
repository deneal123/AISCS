"""Backend-owned task checkpoints and effect intent journal.

Revision ID: 043_harness_state
Revises: 042_ide_checkpoint_orphan_cleanup
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "043_harness_state"
down_revision = "042_ide_checkpoint_orphan_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "harness_task",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint", postgresql.JSONB, nullable=False),
        sa.Column("checkpoint_digest", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id"], ["profile.user_launch.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["profile.user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["profile.chat_threads.thread_id"], ondelete="CASCADE"),
        sa.CheckConstraint("revision >= 0", name="ck_harness_task_revision"),
        sa.CheckConstraint("octet_length(checkpoint::text) <= 1048576", name="ck_harness_checkpoint_size"),
        schema="profile",
    )
    op.create_table(
        "harness_operation",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("intent", postgresql.JSONB, nullable=False),
        sa.Column("intent_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="prepared"),
        sa.Column("receipt", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id"], ["profile.harness_task.task_id"], ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('prepared','dispatched','succeeded','failed','unknown')", name="ck_harness_operation_status"),
        sa.CheckConstraint("(status IN ('prepared','dispatched') AND receipt IS NULL) OR (status IN ('succeeded','failed','unknown') AND receipt IS NOT NULL AND receipt->>'status'=status)", name="ck_harness_operation_receipt"),
        schema="profile",
    )
    op.create_index("ix_harness_task_owner_thread", "harness_task", ["user_id", "thread_id"], schema="profile")


def downgrade() -> None:
    op.drop_table("harness_operation", schema="profile")
    op.drop_index("ix_harness_task_owner_thread", table_name="harness_task", schema="profile")
    op.drop_table("harness_task", schema="profile")
