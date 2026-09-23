"""Credit reservation preflight and deterministic short-circuit responses."""

from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from service.services.chat.domain.confirmation_offer import ConfirmationOfferError
from service.services.chat.infrastructure.chat_worker.message_meta import user_message_meta

logger = logging.getLogger(__name__)

PersistTurn = Callable[..., Awaitable[Any]]
UpdateJobStatus = Callable[..., Awaitable[None]]
EstimateCredits = Callable[..., Awaitable[int]]
EmitShortCircuit = Callable[..., Awaitable[dict[str, Any]]]
OverlayBilling = Callable[[Any, Any], Any]

RESERVATION_TTL_SECONDS = 600
CHARS_PER_TOKEN_ROUGH = 3
RESERVATION_PROMPT_OVERHEAD_TOKENS = 800
RESERVATION_COMPLETION_CEILING_TOKENS = 700
RESERVATION_TOOL_LOOP_FACTOR = 3
DOCUMENT_MAX_PLANNED_SECTIONS = 8
DOCUMENT_SECTION_CONTEXT_TOKENS = 6_000
DOCUMENT_SECTION_COMPLETION_TOKENS = 3_500


def reservation_context_chars(*, file_context: Any, pseudo_session: Any, attachments: Any) -> int:
    """Estimate all prompt-bearing context, not only the current user message."""

    items = getattr(pseudo_session, "_items", None) or []
    return (
        len(file_context or "")
        + sum(len(str(item.get("content") or "")) for item in items)
        + sum(len(str(getattr(item, "text", "") or item)) for item in (attachments or []))
    )


async def estimate_reservation_credits(
    *,
    pg_connector: Any,
    billing_cfg: Any,
    text: str,
    selected_model: str | None,
    context_chars: int = 0,
    route: str | None = None,
) -> int:
    """Compute a conservative hold without changing the eventual usage charge."""

    from service.services.billing.application.pricing_service import PricingService
    from service.services.billing.persistence.pricing_repository import PricingRepository
    from service.shared.token_estimate import estimate_tokens

    base_prompt = estimate_tokens(text) + max(0, int(context_chars)) // CHARS_PER_TOKEN_ROUGH
    if route in {"pdf_gen", "research_pdf_document", "research_pdf_presentation"}:
        # One intent call, one outline call, bounded section calls and one shared
        # protocol repair. This mirrors the S36 authoring state machine instead of
        # charging for the removed four blind full-draft retries.
        section_count = max(2, min(DOCUMENT_MAX_PLANNED_SECTIONS, 2 + base_prompt // 6_000))
        bounded_context = min(
            base_prompt + RESERVATION_PROMPT_OVERHEAD_TOKENS,
            DOCUMENT_SECTION_CONTEXT_TOKENS,
        )
        estimated_prompt = (
            base_prompt
            + (base_prompt + RESERVATION_PROMPT_OVERHEAD_TOKENS)
            + section_count * bounded_context
            + bounded_context
        )
        estimated_completion = (
            900 + 2_000 + (section_count + 1) * DOCUMENT_SECTION_COMPLETION_TOKENS
        )
    else:
        estimated_prompt = (
            base_prompt + RESERVATION_PROMPT_OVERHEAD_TOKENS
        ) * RESERVATION_TOOL_LOOP_FACTOR
        estimated_completion = RESERVATION_COMPLETION_CEILING_TOKENS
    price = await PricingService(PricingRepository(pg_connector), billing_cfg).price_request(
        per_call_usage=[
            {
                "model": selected_model,
                "prompt": estimated_prompt,
                "completion": estimated_completion,
            }
        ],
        tools=[],
        is_complex=False,
    )
    safety = float(getattr(billing_cfg, "reserve_safety", 1.2) or 1.2)
    return max(1, math.ceil(float(price.credits) * safety))


async def emit_expensive_confirmation(
    *,
    publisher: Any,
    job_repo: Any,
    session: Any,
    job_id: str,
    thread_id: str,
    text: str,
    user_id: str | None,
    selected_model: str | None,
    estimated_credits: int,
    attachments: list[Any] | None,
    redis_client: Any,
    confirmation_context: dict[str, Any],
    persist_turn: PersistTurn,
    update_job_status: UpdateJobStatus,
) -> dict[str, Any]:
    """Persist and publish one confirmation offer without exposing the prompt."""

    from service.models.key_value import ProcessingStatus
    from service.services.chat.domain.confirmation_offer import (
        create_confirmation_offer,
        discard_confirmation_offer,
    )

    timestamp = datetime.now(UTC).isoformat()
    source_message_id = str(uuid4())
    assistant_message_id = str(uuid4())
    anchor = await create_confirmation_offer(
        redis_client,
        thread_id=thread_id,
        user_id=str(user_id or ""),
        source_message_id=source_message_id,
        text=text,
        selected_model=selected_model,
        route_override=confirmation_context.get("route_override"),
        resolved_category=confirmation_context.get("resolved_category"),
        input_type=confirmation_context.get("input_type"),
        attachments=attachments,
        file_ids=confirmation_context.get("file_ids"),
    )
    reply = (
        f"Оценка этого запуска — до {estimated_credits:,} кредитов. "
        "Запуск не начат: подтвердите его кнопкой, если хотите продолжить."
    ).replace(",", " ")
    offer = {
        "mode": "expensive_run",
        "label": "дорогой запуск",
        "offer_kind": "tool",
        "estimated_credits": estimated_credits,
        "reason_code": "confirmation_required",
        "offered_at": timestamp,
        "expires_in_sec": 30,
        "offer_id": anchor.offer_id,
        "status": "pending",
    }
    metadata = {
        "kind": "mode_offer",
        "mode_offer": offer,
        "expensive_run_confirmation_required": True,
        "estimated_credits": estimated_credits,
        "selected_model": selected_model or "mws-gpt-alpha",
    }
    try:
        persisted = await persist_turn(
            db_session=session,
            thread_id=thread_id,
            user_text=text,
            assistant_text=reply,
            user_id=user_id,
            user_metadata=user_message_meta(attachments),
            assistant_metadata=metadata,
            user_message_id=source_message_id,
            assistant_message_id=assistant_message_id,
        )
        if persisted is not True:
            raise ConfirmationOfferError("confirmation_unavailable")
    except Exception:
        try:
            await discard_confirmation_offer(redis_client, anchor.offer_id)
        except Exception:
            logger.warning(
                "confirmation cleanup failed",
                extra={"component": "chat", "failure_code": "confirmation_unavailable"},
            )
        raise ConfirmationOfferError("confirmation_unavailable") from None
    publisher.publish_payload(
        {
            "type": "status_update",
            "job_id": job_id,
            "message": "Нужно подтверждение стоимости",
            "metadata": {"kind": "mode_offer", "mode_offer": offer},
            "timestamp": timestamp,
        }
    )
    publisher.publish_payload(
        {
            "type": "stream_chunk",
            "job_id": job_id,
            "data": reply,
            "seq": 0,
            "timestamp": timestamp,
        }
    )
    publisher.publish_payload(
        {
            "type": "stream_complete",
            "job_id": job_id,
            "metadata": metadata,
            "timestamp": timestamp,
        }
    )
    await update_job_status(
        job_repo,
        job_id,
        ProcessingStatus.SUCCESS,
        session,
        user_id,
        {"reply": reply, "file_url": None, "metadata": metadata},
    )
    publisher.publish_payload(
        {
            "type": "agent_reply",
            "job_id": job_id,
            "reply": reply,
            "file_url": None,
            "metadata": metadata,
            "timestamp": timestamp,
        }
    )
    return {
        "status": "success",
        "job_id": job_id,
        "reply": reply,
        "file_url": None,
        "metadata": metadata,
    }


async def emit_insufficient_credits(
    *,
    publisher: Any,
    job_repo: Any,
    session: Any,
    job_id: str,
    thread_id: str,
    text: str,
    user_id: str | None,
    selected_model: str | None,
    reply: str,
    attachments: list[Any] | None,
    persist_turn: PersistTurn,
    update_job_status: UpdateJobStatus,
) -> dict[str, Any]:
    """Close an unfunded job without invoking or charging a provider."""

    from service.models.key_value import ProcessingStatus

    metadata = {
        "insufficient_credits": True,
        "selected_model": selected_model or "mws-gpt-alpha",
    }
    timestamp = datetime.now(UTC).isoformat()
    publisher.publish_payload(
        {
            "type": "stream_chunk",
            "job_id": job_id,
            "data": reply,
            "seq": 0,
            "timestamp": timestamp,
        }
    )
    publisher.publish_payload(
        {
            "type": "stream_complete",
            "job_id": job_id,
            "metadata": metadata,
            "timestamp": timestamp,
        }
    )
    try:
        await persist_turn(
            db_session=session,
            thread_id=thread_id,
            user_text=text,
            assistant_text=reply,
            user_id=user_id,
            user_metadata=user_message_meta(attachments),
        )
    except Exception:
        logger.debug(
            "insufficient-credit turn persistence failed",
            extra={"component": "chat_worker", "failure_code": "persistence"},
        )
    await update_job_status(
        job_repo,
        job_id,
        ProcessingStatus.SUCCESS,
        session,
        user_id,
        {"reply": reply, "file_url": None, "metadata": metadata},
    )
    publisher.publish_payload(
        {
            "type": "agent_reply",
            "job_id": job_id,
            "reply": reply,
            "file_url": None,
            "metadata": metadata,
            "timestamp": timestamp,
        }
    )
    return {
        "status": "success",
        "job_id": job_id,
        "reply": reply,
        "file_url": None,
        "metadata": metadata,
    }


async def reserve_credits_or_short_circuit(
    *,
    pg_connector: Any,
    config: Any,
    publisher: Any,
    job_repo: Any,
    session: Any,
    job_id: str,
    thread_id: str,
    text: str,
    user_id: str | None,
    selected_model: str | None,
    context_chars: int,
    attachments: list[Any] | None,
    expensive_run_confirmed: bool,
    redis_client: Any = None,
    confirmation_context: dict[str, Any] | None = None,
    overlay_billing: OverlayBilling,
    estimate_credits: EstimateCredits,
    emit_expensive: EmitShortCircuit,
    emit_insufficient: EmitShortCircuit,
) -> tuple[dict[str, Any] | None, str | None, int]:
    """Reserve credits before the LLM call and return any completed short circuit."""

    if not user_id:
        return None, None, 0

    try:
        from service.services.billing.application.billing_service import BillingService
        from service.services.billing.persistence.billing_repository import BillingRepository

        billing_config = overlay_billing(pg_connector, config)
        billing = BillingService(BillingRepository(pg_connector), billing_config)
        if not await billing.has_sufficient_credits(user_id):
            result = await emit_insufficient(
                publisher=publisher,
                job_repo=job_repo,
                session=session,
                job_id=job_id,
                thread_id=thread_id,
                text=text,
                user_id=user_id,
                selected_model=selected_model,
                reply=billing_config.insufficient_credits_message,
                attachments=attachments,
            )
            return result, None, 0

        estimated_credits = await estimate_credits(
            pg_connector=pg_connector,
            billing_cfg=billing_config,
            text=text,
            selected_model=selected_model,
            context_chars=context_chars,
            route=str(
                (confirmation_context or {}).get("route_override")
                or (confirmation_context or {}).get("resolved_category")
                or ""
            )
            or None,
        )
        threshold = max(
            0,
            int(
                getattr(
                    billing_config,
                    "expensive_run_confirmation_credits",
                    5_000,
                )
                or 0
            ),
        )
        if threshold and estimated_credits >= threshold and not expensive_run_confirmed:
            result = await emit_expensive(
                publisher=publisher,
                job_repo=job_repo,
                session=session,
                job_id=job_id,
                thread_id=thread_id,
                text=text,
                user_id=user_id,
                selected_model=selected_model,
                estimated_credits=estimated_credits,
                attachments=attachments,
                redis_client=redis_client,
                confirmation_context=confirmation_context or {},
            )
            return result, None, 0
        reservation_id = await billing.reserve(
            user_id,
            credits=estimated_credits,
            ttl_seconds=RESERVATION_TTL_SECONDS,
        )
    except ConfirmationOfferError:
        # An expensive run must never continue when its durable confirmation
        # anchor could not be created. Billing outages retain their historical
        # fail-open behaviour below; confirmation storage is a safety boundary.
        raise
    except Exception:
        logger.debug(
            "credit reservation unavailable; continuing without hold",
            extra={"component": "chat_worker", "failure_code": "billing"},
        )
        return None, None, 0

    if reservation_id is not None:
        return None, reservation_id, int(estimated_credits)

    billing_config = overlay_billing(pg_connector, config)
    result = await emit_insufficient(
        publisher=publisher,
        job_repo=job_repo,
        session=session,
        job_id=job_id,
        thread_id=thread_id,
        text=text,
        user_id=user_id,
        selected_model=selected_model,
        reply=billing_config.insufficient_credits_message,
        attachments=attachments,
    )
    return result, None, 0


__all__ = [
    "emit_expensive_confirmation",
    "emit_insufficient_credits",
    "estimate_reservation_credits",
    "reservation_context_chars",
    "reserve_credits_or_short_circuit",
]
