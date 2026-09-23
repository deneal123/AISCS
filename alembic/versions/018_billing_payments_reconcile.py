"""Pending-платежи для сверки (reconciliation)

При checkout сохраняем payment_id со статусом pending. Если вебхук не дошёл
(эндпоинт лежал / ЮKassa исчерпала ретраи), периодическая celery-задача
перепроверяет статус по API и до-начисляет — иначе оплата терялась бы навсегда.

Revision ID: 018_billing_payments
Revises: 016_user_consent
Create Date: 2026-07-12 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "018_billing_payments"
down_revision = "016_user_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS profile;")
    op.create_table(
        "billing_payments",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # id платежа у провайдера (ЮKassa payment.id). UNIQUE — один платёж = одна
        # строка; повторный checkout с тем же id (теоретически) не задваивает.
        sa.Column("payment_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),  # subscription | topup
        sa.Column("plan", sa.String(64), nullable=True),
        sa.Column("pack_id", sa.String(64), nullable=True),
        # pending → сверяется; reconciled → досверено/начислено; failed → отменён/просрочен.
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'pending'")),
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
        if_not_exists=True,
    )
    op.create_index(
        "ix_profile_billing_payments_payment_id",
        "billing_payments",
        ["payment_id"],
        unique=True,
        schema="profile",
        if_not_exists=True,
    )
    # Выборка «зависших» pending для сверки: по статусу и возрасту.
    op.create_index(
        "ix_profile_billing_payments_status_created",
        "billing_payments",
        ["status", "created_at"],
        schema="profile",
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_profile_billing_payments_status_created",
        table_name="billing_payments",
        schema="profile",
        if_exists=True,
    )
    op.drop_index(
        "ix_profile_billing_payments_payment_id",
        table_name="billing_payments",
        schema="profile",
        if_exists=True,
    )
    op.drop_table("billing_payments", schema="profile", if_exists=True)
