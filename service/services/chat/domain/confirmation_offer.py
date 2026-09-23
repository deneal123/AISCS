"""Opaque Redis anchor for an expensive run awaiting explicit confirmation."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text as sql_text

OFFER_TTL_SEC = 30
ACCEPTED_TTL_SEC = 10 * 60
_PREFIX = "chat:confirmation-offer:"


class ConfirmationOfferError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        self.status_code = {
            "confirmation_expired": 410,
            "confirmation_forbidden": 404,
            "confirmation_busy": 409,
            "confirmation_invalid": 409,
            "confirmation_unavailable": 503,
        }.get(code, 409)
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ConfirmationOfferAnchor:
    offer_id: str
    thread_id: str
    user_id: str
    source_message_id: str
    text: str
    selected_model: str | None
    route_override: str | None
    resolved_category: str | None
    input_type: str | None
    attachments: tuple[dict[str, Any], ...]
    file_ids: tuple[str, ...]
    status: str = "pending"
    job_id: str | None = None
    celery_task_id: str | None = None

    def private_dict(self) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "source_message_id": self.source_message_id,
            "text": self.text,
            "selected_model": self.selected_model,
            "route_override": self.route_override,
            "resolved_category": self.resolved_category,
            "input_type": self.input_type,
            "attachments": list(self.attachments),
            "file_ids": list(self.file_ids),
            "status": self.status,
            "job_id": self.job_id,
            "celery_task_id": self.celery_task_id,
        }

    @classmethod
    def parse(cls, raw: Any) -> ConfirmationOfferAnchor:
        try:
            value = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ConfirmationOfferError("confirmation_invalid") from None
        if not isinstance(value, dict):
            raise ConfirmationOfferError("confirmation_invalid")
        attachments = tuple(
            dict(item) for item in value.get("attachments", [])[:8] if isinstance(item, dict)
        )
        offer = cls(
            offer_id=str(value.get("offer_id") or ""),
            thread_id=str(value.get("thread_id") or ""),
            user_id=str(value.get("user_id") or ""),
            source_message_id=str(value.get("source_message_id") or ""),
            text=str(value.get("text") or ""),
            selected_model=(str(value["selected_model"]) if value.get("selected_model") else None),
            route_override=(str(value["route_override"]) if value.get("route_override") else None),
            resolved_category=(
                str(value["resolved_category"]) if value.get("resolved_category") else None
            ),
            input_type=str(value["input_type"]) if value.get("input_type") else None,
            attachments=attachments,
            file_ids=tuple(str(item) for item in value.get("file_ids", [])[:8]),
            status=str(value.get("status") or "pending"),
            job_id=str(value["job_id"]) if value.get("job_id") else None,
            celery_task_id=(str(value["celery_task_id"]) if value.get("celery_task_id") else None),
        )
        try:
            UUID(offer.source_message_id)
        except (TypeError, ValueError):
            raise ConfirmationOfferError("confirmation_invalid") from None
        if not offer.offer_id or not offer.thread_id or not offer.user_id or not offer.text.strip():
            raise ConfirmationOfferError("confirmation_invalid")
        return offer


def _key(offer_id: str) -> str:
    return f"{_PREFIX}{offer_id}"


def _claim_key(offer_id: str) -> str:
    return f"{_PREFIX}{offer_id}:claim"


async def create_confirmation_offer(
    redis: Any,
    *,
    thread_id: str,
    user_id: str,
    source_message_id: str,
    text: str,
    selected_model: str | None,
    route_override: str | None,
    resolved_category: str | None,
    input_type: str | None,
    attachments: list[Any] | None,
    file_ids: list[Any] | None,
    ttl_sec: int = OFFER_TTL_SEC,
) -> ConfirmationOfferAnchor:
    if redis is None:
        raise ConfirmationOfferError("confirmation_unavailable")
    offer_id = secrets.token_urlsafe(24)
    anchor = ConfirmationOfferAnchor(
        offer_id=offer_id,
        thread_id=str(thread_id),
        user_id=str(user_id),
        source_message_id=str(UUID(str(source_message_id))),
        text=str(text),
        selected_model=selected_model,
        route_override=route_override,
        resolved_category=resolved_category,
        input_type=input_type,
        attachments=tuple(dict(item) for item in (attachments or [])[:8] if isinstance(item, dict)),
        file_ids=tuple(str(item) for item in (file_ids or [])[:8]),
    )
    await redis.set(
        _key(offer_id),
        json.dumps(anchor.private_dict(), ensure_ascii=False, separators=(",", ":")),
        ex=max(1, min(int(ttl_sec), OFFER_TTL_SEC)),
    )
    return anchor


async def claim_confirmation_offer(
    redis: Any,
    offer_id: str,
    *,
    thread_id: str,
    user_id: str,
) -> tuple[ConfirmationOfferAnchor, bool]:
    """Claim exactly once; a completed duplicate returns the original job anchor."""

    if redis is None or not str(offer_id or "").strip():
        raise ConfirmationOfferError("confirmation_unavailable")
    raw = await redis.get(_key(offer_id))
    if raw is None:
        raise ConfirmationOfferError("confirmation_expired")
    anchor = ConfirmationOfferAnchor.parse(raw)
    if anchor.thread_id != str(thread_id) or anchor.user_id != str(user_id):
        raise ConfirmationOfferError("confirmation_forbidden")
    if anchor.status == "accepted" and anchor.job_id:
        return anchor, True
    claimed = await redis.set(_claim_key(offer_id), "1", nx=True, ex=ACCEPTED_TTL_SEC)
    if not claimed:
        # A concurrent consumer may still be creating the job. It must not create a
        # second one; the caller can retry after receiving the bounded busy response.
        raise ConfirmationOfferError("confirmation_busy")
    return anchor, False


async def read_confirmation_offer(
    redis: Any,
    offer_id: str,
    *,
    thread_id: str,
    user_id: str,
) -> ConfirmationOfferAnchor:
    """Read an anchor for request normalization without consuming it."""

    if redis is None or not str(offer_id or "").strip():
        raise ConfirmationOfferError("confirmation_unavailable")
    raw = await redis.get(_key(offer_id))
    if raw is None:
        raise ConfirmationOfferError("confirmation_expired")
    anchor = ConfirmationOfferAnchor.parse(raw)
    if anchor.thread_id != str(thread_id) or anchor.user_id != str(user_id):
        raise ConfirmationOfferError("confirmation_forbidden")
    return anchor


async def mark_confirmation_accepted(
    redis: Any,
    anchor: ConfirmationOfferAnchor,
    *,
    job_id: str,
    celery_task_id: str | None,
) -> ConfirmationOfferAnchor:
    accepted = ConfirmationOfferAnchor(
        **{
            **anchor.private_dict(),
            "attachments": anchor.attachments,
            "file_ids": anchor.file_ids,
            "status": "accepted",
            "job_id": str(job_id),
            "celery_task_id": str(celery_task_id) if celery_task_id else None,
        }
    )
    await redis.set(
        _key(anchor.offer_id),
        json.dumps(accepted.private_dict(), ensure_ascii=False, separators=(",", ":")),
        ex=ACCEPTED_TTL_SEC,
    )
    return accepted


async def release_confirmation_claim(redis: Any, offer_id: str) -> None:
    if redis is not None:
        await redis.delete(_claim_key(offer_id))


async def discard_confirmation_offer(redis: Any, offer_id: str) -> None:
    if redis is not None:
        await redis.delete(_key(offer_id), _claim_key(offer_id))


async def mark_persisted_offer_accepted(
    db_session: Any,
    *,
    thread_id: str,
    offer_id: str,
) -> None:
    """Update the already persisted offer without storing its private anchor."""

    if not str(offer_id or "").strip():
        return
    await db_session.execute(
        sql_text(
            """
            UPDATE profile.chat_messages AS message
            SET "metadata" = jsonb_set(
                jsonb_set(
                    COALESCE(message."metadata", '{}'::jsonb),
                    '{mode_offer,status}',
                    '"accepted"'::jsonb,
                    true
                ),
                '{mode_offer,expired}',
                'false'::jsonb,
                true
            )
            FROM profile.chat_threads AS thread
            WHERE message.thread_id = thread.id
              AND thread.thread_id = :thread_id
              AND message.sender = 'assistant'
              AND message."metadata"->'mode_offer'->>'offer_id' = :offer_id
            """
        ),
        {"thread_id": thread_id, "offer_id": offer_id},
    )


__all__ = [
    "ConfirmationOfferAnchor",
    "ConfirmationOfferError",
    "claim_confirmation_offer",
    "create_confirmation_offer",
    "discard_confirmation_offer",
    "mark_confirmation_accepted",
    "mark_persisted_offer_accepted",
    "read_confirmation_offer",
    "release_confirmation_claim",
]
