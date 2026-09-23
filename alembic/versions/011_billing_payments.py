"""Phase 4 billing: payment provider identifiers on user

Добавляет на profile.user идентификаторы платёжного провайдера (агностично:
customer/subscription ref). Конкретный провайдер (mock/yookassa) подключается
в коде, схема от него не зависит.

Revision ID: 011_billing_payments
Revises: 010_billing_wallets
Create Date: 2026-06-26
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "011_billing_payments"
down_revision = "010_billing_wallets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("payment_customer_id", sa.String(255), nullable=True),
        schema="profile",
    )
    op.add_column(
        "user",
        sa.Column("payment_subscription_id", sa.String(255), nullable=True),
        schema="profile",
    )


def downgrade() -> None:
    op.drop_column("user", "payment_subscription_id", schema="profile")
    op.drop_column("user", "payment_customer_id", schema="profile")
