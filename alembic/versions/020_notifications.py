"""Жизненные уведомления: маркетинговое согласие, отписка, журнал отправок.

Существовавшие согласия (`consent_pd_at`, `consent_transfer_at`) — это 152-ФЗ: обработка
персональных данных и передача LLM-провайдерам. **Согласия на рекламу среди них нет.**

По ФЗ «О рекламе» (ст. 18) рассылка рекламы требует ОТДЕЛЬНОГО предварительного согласия.
Поэтому письма делятся на две категории:

* **сервисные** (подписка истекает, кредиты на исходе, платёж не прошёл) — это состояние
  аккаунта, а не реклама: пользователь должен знать, что с него спишут деньги или что
  доступ пропадёт;
* **маркетинговые** (реактивация: «давно не заходили») — только при `marketing_consent_at`.

`unsubscribed_at` гасит ВСЁ, включая сервисные: если человек явно отписался, слать ему
что-либо — неуважение, даже когда закон формально позволяет.

Журнал `notification_log` нужен не для отчётности, а для идемпотентности: beat крутится
по расписанию, и без уникального dedup_key одно и то же письмо уходило бы каждый прогон.

Revision ID: 020_notifications
Revises: 019_provider_secrets
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "020_notifications"
down_revision = "019_provider_secrets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "marketing_consent_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Separate advertising consent (ФЗ «О рекламе», ст. 18)",
        ),
        schema="profile",
    )
    op.add_column(
        "user",
        sa.Column(
            "unsubscribed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Global opt-out: suppresses ALL mail, including service notices",
        ),
        schema="profile",
    )

    op.create_table(
        "notification_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            UUID(),
            sa.ForeignKey("profile.user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        # Идемпотентность: «то же событие» не должно приводить ко второму письму.
        # Для истекающей подписки это дата конца периода, для платежа — его id, для
        # реактивации — месяц.
        sa.Column("dedup_key", sa.String(128), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.UniqueConstraint("user_id", "kind", "dedup_key", name="uq_notification_log_dedup"),
        schema="profile",
    )
    # Частотный лимит спрашивает «сколько писем ушло этому юзеру за последние N дней».
    op.create_index(
        "ix_notification_log_user_sent",
        "notification_log",
        ["user_id", "sent_at"],
        schema="profile",
    )


def downgrade() -> None:
    op.drop_index("ix_notification_log_user_sent", table_name="notification_log", schema="profile")
    op.drop_table("notification_log", schema="profile")
    op.drop_column("user", "unsubscribed_at", schema="profile")
    op.drop_column("user", "marketing_consent_at", schema="profile")
