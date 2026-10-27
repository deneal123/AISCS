"""Cooperative cancellation boundary for a worker execution."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from service.infrastructure.agents_client.contracts.terminal import valid_run_result

logger = logging.getLogger(__name__)
_CANCEL_OBSERVATION_TIMEOUT_SEC = 2.0


class CancelledByUser(Exception):
    """The user cancelled the run through the bounded Redis control flag."""


async def run_with_cancel(
    awaitable: Any,
    *,
    redis_client: Any,
    celery_task_id: str | None,
    poll_interval: float = 0.6,
    durable_cancel: Callable[[], Awaitable[bool]] | None = None,
) -> Any:
    """Await execution while cooperatively polling its cancellation flag."""

    redis_available = redis_client is not None and bool(celery_task_id)
    if not redis_available and durable_cancel is None:
        return await awaitable

    execution = asyncio.ensure_future(awaitable)
    cancel_key = f"chat:cancel:{celery_task_id}"

    async def poll_cancel() -> bool:
        while True:
            await asyncio.sleep(poll_interval)
            try:
                if redis_available and await asyncio.to_thread(redis_client.get, cancel_key):
                    return True
            except Exception:
                logger.debug(
                    "cancel-flag poll failed; not cancelling",
                    extra={"failure_code": "transport"},
                )
            if durable_cancel is not None:
                try:
                    async with asyncio.timeout(_CANCEL_OBSERVATION_TIMEOUT_SEC):
                        if await durable_cancel() is True:
                            return True
                except Exception:
                    logger.debug(
                        "durable cancel observation unavailable",
                        extra={"failure_code": "persistence"},
                    )

    poller = asyncio.ensure_future(poll_cancel())
    try:
        done, _pending = await asyncio.wait(
            {execution, poller}, return_when=asyncio.FIRST_COMPLETED
        )
        if execution not in done and poller in done and poller.result() is True:
            execution.cancel()
            accepted_result = None
            with contextlib.suppress(asyncio.CancelledError, Exception):
                accepted_result = await execution
            with contextlib.suppress(Exception):
                await asyncio.to_thread(redis_client.delete, cancel_key)
            if valid_run_result(accepted_result):
                # The HTTP reader may have accepted a terminal before cancel
                # interrupted trailing EOF. Keep normal capture and settlement;
                # event usage is never substituted for the canonical result.
                return accepted_result
            raise CancelledByUser("run_cancelled")
        return await execution
    finally:
        for task in (execution, poller):
            if not task.done():
                task.cancel()
        await asyncio.gather(execution, poller, return_exceptions=True)


__all__ = ["CancelledByUser", "run_with_cancel"]
