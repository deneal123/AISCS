"""Observe exact connection ownership without renewing or reacquiring a lost lock."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.execution.lease import _invalidate, _lease_key

_OBSERVATION_INTERVAL_SEC = 1.0
_OBSERVATION_TIMEOUT_SEC = 2.0
_LOCK_HELD = text(
    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
    "AND pid=pg_backend_pid() AND CAST(classid AS bigint)=:high "
    "AND CAST(objid AS bigint)=:low AND objsubid=1 AND granted)"
)


async def _verify(session: Any, job_id: str) -> None:
    key = _lease_key(job_id)
    try:
        async with asyncio.timeout(_OBSERVATION_TIMEOUT_SEC):
            held = await session.scalar(_LOCK_HELD, {"high": key >> 32, "low": key & 0xFFFFFFFF})
        if held is not True:
            raise JobStateUnavailable("Execution ownership unavailable")
    except asyncio.CancelledError:
        raise
    except Exception:
        await _invalidate(session)
        raise JobStateUnavailable("Execution ownership unavailable") from None


async def run_with_execution_ownership[Result](
    session: Any, job_id: str, operation: Callable[[], Awaitable[Result]]
) -> Result:
    """Fail closed on observed loss and join owned execution before leaving scope.

    This is cooperative protection, not a distributed fencing guarantee: a dead
    connection can release the lock before the next bounded observation. Neither
    this observer nor cleanup ever reacquires ownership on a new connection.
    """
    await _verify(session, job_id)

    async def observe() -> None:
        while True:
            await asyncio.sleep(_OBSERVATION_INTERVAL_SEC)
            await _verify(session, job_id)

    execution = asyncio.ensure_future(operation())
    observer = asyncio.create_task(observe())
    try:
        done, _ = await asyncio.wait({execution, observer}, return_when=asyncio.FIRST_COMPLETED)
        if observer in done:
            # Even if execution finished in the same scheduler turn, known loss
            # must not be reported as a verified success by this delivery.
            await observer
            raise JobStateUnavailable("Execution ownership unavailable")
        return await execution
    finally:
        for task in (execution, observer):
            if not task.done():
                task.cancel()
        await asyncio.gather(execution, observer, return_exceptions=True)
