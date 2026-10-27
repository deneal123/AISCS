"""Fail-closed termination before a durable redelivery decision exists."""

from __future__ import annotations

import logging
from typing import Any

from service.services.chat.application.error_handling import map_to_worker_error_payload
from service.services.chat.infrastructure.chat_worker.execution.job_state import (
    HarnessAdmissionUnavailable,
    JobStateUnavailable,
)

logger = logging.getLogger(__name__)


async def abort_unverified_job(
    *, session: Any, publisher: Any, error: JobStateUnavailable, job_id: str
) -> dict[str, Any]:
    """Leave existing terminal/billing state untouched, even if transport also fails."""
    try:
        await session.rollback()
    except Exception:
        logger.warning(
            "unverified job transaction rollback unavailable",
            extra={"component": "chat_worker", "failure_code": "persistence"},
        )
    payload = map_to_worker_error_payload(error, job_id=job_id)
    if isinstance(error, HarnessAdmissionUnavailable):
        # Причина backend-owned, без exception text, SQL, содержимого или capability.
        # Это уведомление об отказе, не новый terminal/settlement и не повтор dispatch.
        payload["error"] = error.public_message
    try:
        publisher.publish_payload(payload)
    except Exception:
        logger.warning(
            "unverified job notification unavailable",
            extra={"component": "chat_worker", "failure_code": "transport"},
        )
    return {
        "status": "error",
        "error": payload["error"],
        "error_code": payload["error_code"],
        "status_code": payload["status_code"],
    }
