"""Bind simulation recovery to its execution queue.

Revision ID: 050_simulation_execution_queue
Revises: 049_simulation_runs
"""

import sqlalchemy as sa

from alembic import op

revision = "050_simulation_execution_queue"
down_revision = "049_simulation_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "simulation_run",
        sa.Column("execution_queue", sa.String(100), nullable=False,
                  server_default="simulation"),
        schema="profile",
    )
    op.create_index("ix_simulation_run_execution_queue", "simulation_run",
                    ["execution_queue"], schema="profile")


def downgrade() -> None:
    op.drop_index("ix_simulation_run_execution_queue", table_name="simulation_run",
                  schema="profile")
    op.drop_column("simulation_run", "execution_queue", schema="profile")
