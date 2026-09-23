"""Phase 3 billing: user wallet fields + quota uniqueness for provisioning

Добавляет на profile.user поля кошелька докупки и тариф, а также уникальное
ограничение на (user_id, period_start) в token_quotas — чтобы безопасно
провизионить квоту периода через INSERT ... ON CONFLICT DO NOTHING.

Revision ID: 010_billing_wallets
Revises: 009_billing_pricing
Create Date: 2026-06-26
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "010_billing_wallets"
down_revision = "009_billing_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("plan", sa.String(32), nullable=False, server_default="free"),
        schema="profile",
    )
    op.add_column(
        "user",
        sa.Column(
            "topup_credit_balance",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        schema="profile",
    )
    # Нужно для ON CONFLICT (user_id, period_start) при провижининге квоты периода.
    op.create_unique_constraint(
        "uq_profile_token_quotas_user_period_start",
        "token_quotas",
        ["user_id", "period_start"],
        schema="profile",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_profile_token_quotas_user_period_start",
        "token_quotas",
        schema="profile",
        type_="unique",
    )
    op.drop_column("user", "topup_credit_balance", schema="profile")
    op.drop_column("user", "plan", schema="profile")
