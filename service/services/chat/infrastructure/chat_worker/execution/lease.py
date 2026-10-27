"""Connection-scoped execution ownership, separate from job-state transactions."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import text

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable

logger = logging.getLogger(__name__)
_LEASE_IO_TIMEOUT_SEC = 2.0


def _lease_key(job_id: str) -> int:
    identity = UUID(job_id)
    digest = hashlib.sha256(b"gpthub:chat:execution:v1:" + identity.bytes).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


async def _invalidate(session: Any) -> None:
    """Never return a possibly locked physical connection to the pool."""
    try:
        await session.invalidate()
    except Exception:
        raise JobStateUnavailable("Execution ownership unavailable") from None


@asynccontextmanager
async def claim_execution_session(connector: Any, job_id: str) -> AsyncIterator[Any | None]:
    """Try one job lock on a dedicated session; no payload or identifiers are logged.

    The session is retained until release and is never used for job writes. Its
    session-level advisory lock is unaffected by other transactions' commits.
    Contention yields false: it is not a terminal failure of the durable job.
    """
    try:
        key = _lease_key(job_id)
    except (ValueError, TypeError, AttributeError):
        raise JobStateUnavailable("Execution ownership unavailable") from None

    async with connector.get_session_context() as session:
        try:
            async with asyncio.timeout(_LEASE_IO_TIMEOUT_SEC):
                acquired = await session.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
                )
            if not isinstance(acquired, bool):
                raise JobStateUnavailable("Execution ownership unavailable")
        except asyncio.CancelledError:
            await _invalidate(session)
            raise
        except Exception:
            await _invalidate(session)
            raise JobStateUnavailable("Execution ownership unavailable") from None

        try:
            yield session if acquired else None
        finally:
            if acquired:
                try:
                    async with asyncio.timeout(_LEASE_IO_TIMEOUT_SEC):
                        released = await session.scalar(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                        )
                    if released is not True:
                        await _invalidate(session)
                except asyncio.CancelledError:
                    await _invalidate(session)
                    raise
                except Exception:
                    await _invalidate(session)
                    logger.warning(
                        "execution lease cleanup unavailable",
                        extra={"component": "chat_worker", "failure_code": "persistence"},
                    )


@asynccontextmanager
async def claim_job_execution(connector: Any, job_id: str) -> AsyncIterator[bool]:
    """Boolean compatibility projection of the same dedicated session lease."""
    async with claim_execution_session(connector, job_id) as session:
        yield session is not None
