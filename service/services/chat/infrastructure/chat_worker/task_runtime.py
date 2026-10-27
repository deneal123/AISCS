"""Изолированный loop задания Celery с очисткой ресурсов до его закрытия."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable

from service.infrastructure.database.postgresql import PgConnector

logger = logging.getLogger(__name__)


async def _await_result[Result](awaitable: Awaitable[Result]) -> Result:
    return await awaitable


async def _shutdown_task_resources() -> None:
    # Дочерние задачи могут ещё владеть сессиями: сначала даём им завершить finally.
    current = asyncio.current_task()
    pending = [task for task in asyncio.all_tasks() if task is not current]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    for task in pending:
        if not task.cancelled() and task.exception() is not None:
            logger.warning(
                "worker background cleanup failed",
                extra={"component": "chat_worker", "failure_code": "background_cleanup"},
            )
    await asyncio.get_running_loop().shutdown_asyncgens()
    await PgConnector.close_current_loop()


def run_coroutine[Result](awaitable: Awaitable[Result]) -> Result:
    # Runner дополнительно завершает executor и поздние фоновые задачи. Очистка
    # пула выполняется в исходном loop, а не при создании следующего задания.
    with asyncio.Runner() as runner:
        try:
            return runner.run(_await_result(awaitable))
        finally:
            runner.run(_shutdown_task_resources())


__all__ = ["run_coroutine"]
