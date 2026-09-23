"""User consent columns (152-ФЗ: раздельные согласия при регистрации).

С 01.09.2025 согласие на обработку ПДн оформляется отдельно (раздельные чекбоксы
в регистрации). Фиксируем факт/время/версию: consent_pd_at — общее согласие на
обработку, consent_transfer_at — отдельное согласие на передачу LLM-провайдерам и
трансграничную передачу, consent_version — версия документов. Существующие
пользователи — NULL (грандфатерены; согласие предшествует механизму).

Revision ID: 016_user_consent
Revises: 015_user_is_active
Create Date: 2026-07-10
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "016_user_consent"
down_revision = "015_user_is_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("consent_pd_at", sa.DateTime(timezone=True), nullable=True),
        schema="profile",
    )
    op.add_column(
        "user",
        sa.Column("consent_transfer_at", sa.DateTime(timezone=True), nullable=True),
        schema="profile",
    )
    op.add_column(
        "user",
        sa.Column("consent_version", sa.String(length=50), nullable=True),
        schema="profile",
    )


def downgrade() -> None:
    op.drop_column("user", "consent_version", schema="profile")
    op.drop_column("user", "consent_transfer_at", schema="profile")
    op.drop_column("user", "consent_pd_at", schema="profile")
