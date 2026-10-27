"""Scientific simulation runs, attempts and artifact ownership.

Revision ID: 049_simulation_runs
Revises: 048_retained_expiry
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "049_simulation_runs"
down_revision = "048_retained_expiry"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE service_type ADD VALUE IF NOT EXISTS 'SIMULATION'")
    common = [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
              sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now())]
    op.create_table("simulation_run",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("user_id", postgresql.UUID(), sa.ForeignKey("profile.user.id"), nullable=False),
        sa.Column("job_id", postgresql.UUID(), sa.ForeignKey("profile.user_launch.id"), nullable=False, unique=True),
        sa.Column("request_id", postgresql.UUID(), nullable=False),
        sa.Column("parent_run_id", postgresql.UUID(), sa.ForeignKey("profile.simulation_run.id")),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("configuration_sha256", sa.String(64), nullable=False),
        sa.Column("attempt_id", postgresql.UUID()), sa.Column("claim_token", postgresql.UUID()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("result", postgresql.JSONB()), sa.Column("error", sa.String(500)),
        *common, sa.UniqueConstraint("user_id", "request_id", name="uq_simulation_request"), schema="profile")
    op.create_index("ix_simulation_run_user_id", "simulation_run", ["user_id"], schema="profile")
    op.create_index("ix_simulation_run_state", "simulation_run", ["state"], schema="profile")
    op.create_table("simulation_attempt",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("run_id", postgresql.UUID(), sa.ForeignKey("profile.simulation_run.id"), nullable=False),
        sa.Column("state", sa.String(24), nullable=False), sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("executor", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()), schema="profile")
    op.create_index("ix_simulation_attempt_run_id", "simulation_attempt", ["run_id"], schema="profile")
    op.create_table("simulation_artifact",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("run_id", postgresql.UUID(), sa.ForeignKey("profile.simulation_run.id"), nullable=False),
        sa.Column("file_id", postgresql.UUID(), sa.ForeignKey("profile.user_file.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "name", name="uq_simulation_artifact"), schema="profile")
    op.create_index("ix_simulation_artifact_run_id", "simulation_artifact", ["run_id"], schema="profile")


def downgrade():
    op.drop_table("simulation_artifact", schema="profile")
    op.drop_table("simulation_attempt", schema="profile")
    op.drop_table("simulation_run", schema="profile")
    # PostgreSQL enum values are intentionally not removed from persisted history.
