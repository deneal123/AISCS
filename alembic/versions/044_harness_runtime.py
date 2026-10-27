"""Private admission, fenced execution binding and paid-call grants.

Revision ID: 044_harness_runtime
Revises: 043_harness_state
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "044_harness_runtime"
down_revision = "043_harness_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("harness_task", "checkpoint", nullable=True, schema="profile")
    op.alter_column("harness_task", "checkpoint_digest", nullable=True, schema="profile")
    for column in (
        sa.Column("admission", postgresql.JSONB),
        sa.Column("continuation", postgresql.JSONB),
        sa.Column("tariff", postgresql.JSONB),
        sa.Column("active_job_id", postgresql.UUID(as_uuid=True)),
        sa.Column("fencing_epoch", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("settled_credits", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("settlement", postgresql.JSONB),
        sa.Column("usage_history", postgresql.JSONB, nullable=False, server_default="[]"),
    ):
        op.add_column("harness_task", column, schema="profile")
    op.execute("UPDATE profile.harness_task SET active_job_id=task_id")
    op.create_foreign_key(
        "fk_harness_active_job",
        "harness_task",
        "user_launch",
        ["active_job_id"],
        ["id"],
        source_schema="profile",
        referent_schema="profile",
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_harness_active_job", "harness_task", ["active_job_id"], schema="profile", unique=True
    )
    op.create_table(
        "harness_grant",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request", postgresql.JSONB, nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("state", sa.String(12), nullable=False, server_default="allocated"),
        sa.Column("receipt", postgresql.JSONB),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["task_id"], ["profile.harness_task.task_id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "state IN ('allocated','dispatched','succeeded','unknown','waived')",
            name="ck_harness_grant_state",
        ),
        schema="profile",
    )


def downgrade() -> None:
    op.drop_table("harness_grant", schema="profile")
    op.drop_index("ix_harness_active_job", table_name="harness_task", schema="profile")
    op.drop_constraint("fk_harness_active_job", "harness_task", schema="profile")
    for column in (
        "usage_history",
        "settlement",
        "settled_credits",
        "fencing_epoch",
        "active_job_id",
        "tariff",
        "continuation",
        "admission",
    ):
        op.drop_column("harness_task", column, schema="profile")
    # Unsealed admissions have no v1 equivalent; do not silently delete them.
    op.alter_column("harness_task", "checkpoint", nullable=False, schema="profile")
    op.alter_column("harness_task", "checkpoint_digest", nullable=False, schema="profile")
