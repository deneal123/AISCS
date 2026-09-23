"""Failure finalization for a chat worker run.

The caller owns the active transaction.  This module performs compensating
actions only after that transaction has been rolled back.
"""

from __future__ import annotations

import logging
from typing import Any

from service.services.chat.application.error_handling import map_to_worker_error_payload
from service.services.chat.infrastructure.chat_worker.cancellation import CancelledByUser
from service.services.chat.infrastructure.chat_worker.turn_result import interrupted_reply_text

logger = logging.getLogger(__name__)


async def handle_worker_failure(
    *,
    pg_connector: Any,
    config: Any,
    job_repo: Any,
    publisher: Any,
    exc: Exception,
    job_id: str,
    thread_id: str,
    user_text: str,
    user_id: str | None,
    reservation_id: str | None,
    charged_credits: int,
    streamed_parts: list[str],
    attachments: list[Any] | None,
    overlay_billing: Any,
    release_reservation: Any,
    mark_job_failed: Any,
    persist_partial_turn: Any,
    user_message_metadata: Any,
) -> None:
    """Compensate billing, persist terminal state, and publish a safe failure."""

    if charged_credits > 0:
        try:
            from service.services.billing.application.billing_service import BillingService
            from service.services.billing.persistence.billing_repository import BillingRepository

            billing_cfg = overlay_billing(pg_connector, config)
            await BillingService(BillingRepository(pg_connector), billing_cfg).refund(
                user_id,
                credits=charged_credits,
                reason="job_failed_after_charge",
            )
        except Exception:
            logger.error(
                "credit refund failed",
                extra={"component": "billing", "failure_code": "refund"},
            )
    else:
        await release_reservation(
            pg_connector=pg_connector,
            config=config,
            reservation_id=reservation_id,
        )

    await mark_job_failed(pg_connector, job_repo, job_id, user_id)

    interrupted_text = interrupted_reply_text(
        streamed_parts,
        cancelled=isinstance(exc, CancelledByUser),
    )
    if interrupted_text:
        await persist_partial_turn(
            pg_connector,
            thread_id,
            user_text,
            interrupted_text,
            user_id,
            user_message_metadata(attachments),
        )

    publisher.publish_payload(map_to_worker_error_payload(exc, job_id=job_id))


__all__ = ["handle_worker_failure"]
