"""Admin panel: user.is_admin flag + app_settings runtime overlay

Добавляет роль администратора в БД (в дополнение к env SERVICE__ADMIN_USER_IDS)
и таблицу runtime-настроек app_settings (key→JSONB), редактируемых из админки
без передеплоя.

Revision ID: 012_admin_panel
Revises: 011_billing_payments
Create Date: 2026-06-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "012_admin_panel"
down_revision = "011_billing_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS profile;")

    op.add_column(
        "user",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="profile",
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="profile",
    )


def downgrade() -> None:
    op.drop_table("app_settings", schema="profile")
    op.drop_column("user", "is_admin", schema="profile")
