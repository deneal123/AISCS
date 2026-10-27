"""One isolated destination and one Git dispatch per clone intent.

Revision ID: 036_ide_clone_intents
Revises: 035_ide_onboarding_identity
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "036_ide_clone_intents"
down_revision = "035_ide_onboarding_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ide_clone_intent",
        sa.Column("intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="reserved"),
        sa.Column("started_at", sa.BigInteger(), nullable=True),
        sa.Column("code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("user_id", "thread_id", "intent_id"),
        sa.UniqueConstraint("repository_id", name="uq_ide_clone_destination"),
        sa.ForeignKeyConstraint(
            ["source_repository_id"],
            ["profile.ide_repository.repository_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["profile.ide_repository.repository_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("source_repository_id <> repository_id", name="ck_ide_clone_isolated"),
        sa.CheckConstraint("request_digest ~ '^[0-9a-f]{64}$'", name="ck_ide_clone_digest"),
        sa.CheckConstraint(
            "state IN ('reserved','cloning','complete','failed','unconfirmed')",
            name="ck_ide_clone_state",
        ),
        sa.CheckConstraint(
            "(state='reserved') = (started_at IS NULL)", name="ck_ide_clone_started"
        ),
        schema="profile",
    )


def downgrade() -> None:
    op.drop_table("ide_clone_intent", schema="profile")
