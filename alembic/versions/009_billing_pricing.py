"""Phase 2 billing: model pricing registry + daily usage aggregates

Создаёт ручной price-registry (profile.model_pricing) и суточные агрегаты
потребления (profile.usage_daily). Также сливает две существующие головы
alembic (ветвление от 016_billing_idx_trgs): 005_user_launch_type_to_enum и
008_drop_legacy_tables — после этой ревизии голова снова одна.

Revision ID: 009_billing_pricing
Revises: 005_user_launch_type_to_enum, 008_drop_legacy_tables
Create Date: 2026-06-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "009_billing_pricing"
down_revision = ("005_user_launch_type_to_enum", "008_drop_legacy_tables")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS profile;")

    # Ручной реестр цен моделей (₽ за 1K токенов). MWS не отдаёт pricing —
    # значения задаёт админ. margin_override — необязательная пер-модельная маржа.
    op.create_table(
        "model_pricing",
        sa.Column("model_id", sa.String(255), primary_key=True),
        sa.Column("price_in_rub_per_1k", sa.Numeric(12, 6), nullable=False),
        sa.Column("price_out_rub_per_1k", sa.Numeric(12, 6), nullable=False),
        sa.Column("margin_override", sa.Numeric(6, 3), nullable=True),
        sa.Column("model_class", sa.String(32), nullable=True),
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

    # Суточные агрегаты потребления для аналитики/админки (быстрые выборки
    # без сканирования billing_events). Ключ (user_id, day), апсертится.
    op.create_table(
        "usage_daily",
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("credits", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("raw_cost_rub", sa.Numeric(14, 6), nullable=False, server_default="0"),
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
        sa.PrimaryKeyConstraint("user_id", "day", name="pk_profile_usage_daily"),
        schema="profile",
    )
    op.create_index("ix_profile_usage_daily_day", "usage_daily", ["day"], schema="profile")


def downgrade() -> None:
    op.drop_index("ix_profile_usage_daily_day", table_name="usage_daily", schema="profile")
    op.drop_table("usage_daily", schema="profile")
    op.drop_table("model_pricing", schema="profile")
