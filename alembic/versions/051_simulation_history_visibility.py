"""Preserve dependent simulation results when removing an item from history.

Revision ID: 051_sim_history_visibility
Revises: 050_simulation_execution_queue
"""
from alembic import op
import sqlalchemy as sa

revision = "051_sim_history_visibility"
down_revision = "050_simulation_execution_queue"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("simulation_run", sa.Column("hidden_from_history", sa.Boolean(),
                  nullable=False, server_default=sa.false()), schema="profile")


def downgrade():
    op.drop_column("simulation_run", "hidden_from_history", schema="profile")
