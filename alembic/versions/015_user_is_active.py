"""User is_active flag (admin block / unblock).

Добавляем `is_active` в profile.user. Существующие пользователи — активны по
умолчанию. Блокировка гейтит вход (и OTP-verify) и сносит сессии пользователя;
управляется из админ-панели.

Revision ID: 015_user_is_active
Revises: 014_user_email_verified
Create Date: 2026-07-09
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "015_user_is_active"
down_revision = "014_user_email_verified"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        schema="profile",
    )


def downgrade() -> None:
    op.drop_column("user", "is_active", schema="profile")
