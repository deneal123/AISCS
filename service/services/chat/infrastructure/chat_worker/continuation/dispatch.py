"""Best-effort wakeup plus periodic fallback, gated off until the full UI rollout."""

import asyncio
import logging

from celery import shared_task

logger = logging.getLogger(__name__)
DISPATCH_TASK = "service.infrastructure.messaging.tasks.dispatch_human_question_children"


def trigger_human_question_dispatch() -> None:
    from service.settings import config

    if config.human_questions.enabled is not True:
        return
    try:
        from service.infrastructure.messaging.celery_app import celery_app

        # BackgroundTasks выполняет этот код в другом потоке. shared_task там
        # может разрешиться в default app и отправить сообщение в другой брокер.
        celery_app.send_task(DISPATCH_TASK, retry=False)
    except Exception:
        logger.warning(
            "question dispatch wakeup deferred",
            extra={
                "component": "human_question",
                "failure_code": "unavailable",
            },
        )


@shared_task(
    name=DISPATCH_TASK,
    soft_time_limit=100,
    time_limit=120,
)
def dispatch_human_question_children() -> dict:
    from service.settings import Config

    config = Config()
    if config.human_questions.enabled is not True:
        return {"status": "skipped", "reason": "disabled"}

    async def dispatch():
        from service.infrastructure.database.postgresql import PgConnector
        from service.infrastructure.messaging.ports import CeleryJobQueuePort
        from service.services.chat.application.human_questions.dispatch import (
            dispatch_question_children,
        )
        from service.services.chat.persistence.human_questions.dispatch import (
            HumanQuestionDispatchRepository,
        )

        connector = PgConnector(config.pg)
        try:
            return await dispatch_question_children(
                HumanQuestionDispatchRepository(connector),
                CeleryJobQueuePort(),
                enabled=True,
            )
        finally:
            await connector.close()

    try:
        return {"status": "success", **asyncio.run(dispatch())}
    except Exception:
        logger.warning(
            "question dispatch maintenance deferred",
            extra={
                "component": "human_question",
                "failure_code": "unavailable",
            },
        )
        return {"status": "deferred", "reason": "unavailable"}
