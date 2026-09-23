"""Секреты провайдеров: зашифрованные API-ключи для runtime-замены

Позволяет менять API-ключи LLM-провайдеров из админки без перезапуска стека.
Значения хранятся зашифрованными (Fernet поверх AUTH__SECRET); наружу через API
ключ никогда не отдаётся (только статус «настроен/дата»). Отдельная таблица, а не
app_settings — чистая граница секретов (реестр настроек их намеренно исключает).

Revision ID: 019_provider_secrets
Revises: 018_billing_payments
Create Date: 2026-07-13 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "019_provider_secrets"
down_revision = "018_billing_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS profile;")
    op.create_table(
        "provider_secrets",
        # имя провайдера (openai/openrouter/routerai/mws/gigachat) = первичный ключ
        sa.Column("provider", sa.String(64), primary_key=True),
        # Fernet-шифртекст API-ключа/authorization_key провайдера
        sa.Column("secret_enc", sa.Text(), nullable=False),
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
    op.drop_table("provider_secrets", schema="profile")
