"""Email verification flag on profile.user.

Регистрация теперь подтверждается кодом, а вход требует OTP по email. Добавляем
`email_verified` (+ `verified_at`) и грандфатерим все существующие аккаунты как
подтверждённые — они появились до внедрения подтверждения почты и не должны
блокироваться.

Revision ID: 014_user_email_verified
Revises: 013_user_memory_facts
Create Date: 2026-07-08
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "014_user_email_verified"
down_revision = "013_user_memory_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        schema="profile",
    )
    op.add_column(
        "user",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        schema="profile",
    )
    # Грандфатеринг: все текущие пользователи считаются подтверждёнными.
    op.execute('UPDATE profile."user" SET email_verified = true, verified_at = now()')


def downgrade() -> None:
    op.drop_column("user", "verified_at", schema="profile")
    op.drop_column("user", "email_verified", schema="profile")
