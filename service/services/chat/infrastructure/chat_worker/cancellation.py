"""Cooperative cancellation boundary for a worker execution."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class CancelledByUser(Exception):
    """The user cancelled the run through the bounded Redis control flag."""


async def run_with_cancel(
    awaitable: Any,
    *,
    redis_client: Any,
    celery_task_id: str | None,
    poll_interval: float = 0.6,
) -> Any:
    """Await execution while cooperatively polling its cancellation flag."""

    if redis_client is None or not celery_task_id:
        return await awaitable

    execution = asyncio.ensure_future(awaitable)
    cancel_key = f"chat:cancel:{celery_task_id}"

    async def poll_cancel() -> bool:
        while True:
            await asyncio.sleep(poll_interval)
            try:
                if await asyncio.to_thread(redis_client.get, cancel_key):
                    return True
            except Exception:
                logger.debug(
                    "cancel-flag poll failed; not cancelling",
                    extra={"failure_code": "transport"},
                )
                return False

    poller = asyncio.ensure_future(poll_cancel())
    done, _pending = await asyncio.wait({execution, poller}, return_when=asyncio.FIRST_COMPLETED)
    if execution not in done and poller in done and poller.result() is True:
        execution.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await execution
        with contextlib.suppress(Exception):
            await asyncio.to_thread(redis_client.delete, cancel_key)
        raise CancelledByUser("run_cancelled")

    poller.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poller
    return await execution


__all__ = ["CancelledByUser", "run_with_cancel"]
