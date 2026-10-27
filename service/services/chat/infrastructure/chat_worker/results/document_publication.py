"""Bind private document delivery to the exact assistant persisted by this job."""

from __future__ import annotations

import logging
from typing import Any
from uuid import NAMESPACE_URL, uuid5

logger = logging.getLogger(__name__)


def document_origin_message_id(job_id: str) -> str:
    """Recover the same opaque assistant ID without changing public metadata."""
    return str(uuid5(NAMESPACE_URL, f"chat-document-message:{job_id}"))


async def enqueue_document_intent(
    session: Any,
    *,
    user_id: str | None,
    thread_id: str,
    workspace_id: str,
    job_id: str,
    descriptors: list[dict],
    origin_message_id: str,
) -> None:
    from service.infrastructure.agents_client.ports import resolve_user_uuid
    from service.services.chat.persistence.documents.publication import enqueue

    await enqueue(
        session,
        user_id=resolve_user_uuid(user_id, anonymous_fallback=True),
        thread_id=thread_id,
        workspace_id=workspace_id,
        billing_job_id=job_id,
        descriptors=tuple(descriptors),
        origin_message_id=origin_message_id,
    )


def trigger_document_delivery() -> None:
    """Broker notification is best-effort after the transaction is committed."""
    try:
        from service.infrastructure.messaging.tasks import deliver_document_publications

        deliver_document_publications.delay()
    except Exception:
        logger.warning(
            "document publication trigger deferred",
            extra={"component": "document_publication", "failure_code": "unavailable"},
        )
