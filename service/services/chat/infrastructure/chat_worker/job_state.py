"""Durable job-state transitions and Celery redelivery protection.

The helpers in this module deliberately know nothing about chat execution.  They
only translate opaque worker identifiers for the repository and enforce the
idempotency decision made before an expensive provider call.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

FetchStatus = Callable[..., Awaitable[tuple[Any | None, dict[str, Any] | None]]]
UpdateStatus = Callable[..., Awaitable[None]]


def _as_uuid(value: Any, *, anonymous: bool = False) -> UUID:
    if value is None and anonymous:
        return UUID("00000000-0000-0000-0000-000000000000")
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


async def fetch_job_status(
    job_repo: Any,
    job_id: str,
    session: Any,
    user_id: Any,
) -> tuple[Any | None, dict[str, Any] | None]:
    """Return a bounded status snapshot used by the redelivery latch."""

    try:
        job = await job_repo.fetch_job_by_id(
            _as_uuid(job_id),
            _as_uuid(user_id, anonymous=True),
            session=session,
        )
        if not job:
            return None, None
        payload = job.payload if isinstance(job.payload, dict) else {}
        return job.status, payload
    except Exception:
        logger.error(
            "job status fetch failed",
            extra={"component": "chat_worker", "failure_code": "persistence"},
        )
        return None, None


async def update_job_status(
    job_repo: Any,
    job_id: str,
    status: Any,
    session: Any,
    user_id: Any,
    result_data: dict[str, Any] | None = None,
) -> None:
    """Update one job in the caller-owned transaction."""

    try:
        job = await job_repo.fetch_job_by_id(
            _as_uuid(job_id),
            _as_uuid(user_id, anonymous=True),
            session=session,
        )
        if not job:
            return
        job.status = status
        if result_data:
            payload = job.payload if isinstance(job.payload, dict) else {}
            payload.update(result_data)
            job.payload = payload
        await job_repo.update_job_status(job, session=session)
    except Exception:
        logger.error(
            "job status update failed",
            extra={"component": "chat_worker", "failure_code": "persistence"},
        )


async def mark_job_failed_committed(
    pg_connector: Any,
    job_repo: Any,
    job_id: str,
    user_id: Any,
    *,
    update_status: UpdateStatus = update_job_status,
) -> None:
    """Persist FAILURE in a fresh transaction after the run transaction rolled back."""

    from service.models.key_value import ProcessingStatus

    try:
        async with pg_connector.get_session_context() as fail_session:
            await update_status(
                job_repo,
                job_id,
                ProcessingStatus.FAILURE,
                fail_session,
                user_id,
            )
            await fail_session.commit()
    except Exception:
        logger.error(
            "job failure status commit failed",
            extra={"component": "chat_worker", "failure_code": "persistence"},
        )


async def redelivery_short_circuit(
    job_repo: Any,
    job_id: str,
    session: Any,
    user_id: Any,
    *,
    fetch_status: FetchStatus = fetch_job_status,
) -> dict[str, Any] | None:
    """Return a stored terminal envelope instead of repeating an expensive run."""

    from service.models.key_value import ProcessingStatus

    status, payload = await fetch_status(job_repo, job_id, session, user_id)
    payload = payload or {}
    if status == ProcessingStatus.SUCCESS:
        logger.info(
            "completed job redelivery skipped",
            extra={"component": "chat_worker", "status": "success"},
        )
        return {
            "status": "success",
            "job_id": job_id,
            "reply": payload.get("reply", ""),
            "file_url": payload.get("file_url"),
            "metadata": payload.get("metadata", {}),
        }
    if status == ProcessingStatus.FAILURE:
        logger.info(
            "failed job redelivery skipped",
            extra={"component": "chat_worker", "status": "failure"},
        )
        return {"status": "error", "error": "Job already failed"}
    return None


__all__ = [
    "fetch_job_status",
    "mark_job_failed_committed",
    "redelivery_short_circuit",
    "update_job_status",
]
