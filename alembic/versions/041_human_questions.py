"""Separate question lifecycle from immutable accepted job results.

Revision ID: 041_human_questions
Revises: 040_ide_checkpoint_accounting
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "041_human_questions"
down_revision = "040_ide_checkpoint_accounting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "human_question",
        sa.Column("question_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_job_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("surface", sa.String(3), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.String(128), nullable=False),
        sa.Column("prompt", postgresql.JSONB, nullable=False),
        sa.Column("continuation", postgresql.JSONB, nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("state", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answer_intent_id", postgresql.UUID(as_uuid=True)),
        sa.Column("answer", postgresql.JSONB),
        sa.Column("resume_job_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["source_job_id"], ["profile.user_launch.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["profile.chat_threads.thread_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["profile.user.id"], ondelete="CASCADE"),
        sa.CheckConstraint("surface IN ('ide','pdf')", name="ck_human_question_surface"),
        sa.CheckConstraint(
            "state IN ('pending','accepted','cancelled','expired')", name="ck_human_question_state"
        ),
        sa.CheckConstraint(
            "(state='accepted' AND answer_intent_id IS NOT NULL AND answer IS NOT NULL "
            "AND resume_job_id IS NOT NULL AND answered_at IS NOT NULL) OR "
            "(state<>'accepted' AND answer_intent_id IS NULL AND answer IS NULL "
            "AND resume_job_id IS NULL AND answered_at IS NULL)",
            name="ck_human_question_answer",
        ),
        schema="profile",
    )
    op.create_index(
        "ix_human_question_owner_thread",
        "human_question",
        ["user_id", "thread_id", "created_at"],
        schema="profile",
    )


def downgrade() -> None:
    op.drop_index("ix_human_question_owner_thread", table_name="human_question", schema="profile")
    op.drop_table("human_question", schema="profile")
