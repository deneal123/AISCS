"""Периодическая рассылка жизненных уведомлений (celery beat, очередь maintenance)."""

from __future__ import annotations

import asyncio
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="service.services.notifications.tasks.send_lifecycle_notifications",
    queue="maintenance",
)
def send_lifecycle_notifications(self) -> dict:
    """Один прогон по всем триггерам.

    Best-effort: сбой рассылки не должен ронять воркер и не должен ретраиться агрессивно —
    идемпотентность держится на dedup_key, но повторные прогоны всё равно стоят запросов
    к БД, а письмо уже ушло.
    """
    from service.infrastructure.mail.smtp_mailer import SmtpMailer
    from service.services.chat.infrastructure.chat_worker import ChatWorkerDependencyFactory
    from service.services.notifications.notification_service import NotificationService
    from service.settings import config

    if not config.notifications.enabled:
        return {"skipped": "disabled"}

    pg_connector = ChatWorkerDependencyFactory().create_pg_connector(config)
    service = NotificationService(pg_connector, SmtpMailer(config.email), config)

    async def run() -> dict:
        try:
            return await service.run()
        except Exception:
            logger.exception("рассылка уведомлений упала")
            return {}

    return asyncio.run(run())
