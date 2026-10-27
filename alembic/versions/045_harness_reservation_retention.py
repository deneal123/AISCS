"""Retain admitted task obligations independently of reservation TTL.

Revision ID: 045_harness_holds
Revises: 044_harness_runtime
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "045_harness_holds"
down_revision = "044_harness_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deliberately no cascading FK: deleting a task must not release an unknown debt.
    op.add_column(
        "token_reservations",
        sa.Column("harness_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="profile",
    )
    op.execute(
        "UPDATE profile.token_reservations r SET harness_task_id=t.task_id "
        "FROM profile.harness_task t WHERE r.status='reserved' "
        "AND r.user_id=t.user_id AND r.reservation_id="
        "CAST(t.admission->>'reservation_id' AS uuid)"
    )


def downgrade() -> None:
    # Removing retention with outstanding obligations would silently free money.
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM profile.token_reservations "
        "WHERE status='reserved' AND harness_task_id IS NOT NULL) THEN "
        "RAISE EXCEPTION 'Outstanding harness reservations require reconciliation'; "
        "END IF; END $$"
    )
    op.drop_column("token_reservations", "harness_task_id", schema="profile")
