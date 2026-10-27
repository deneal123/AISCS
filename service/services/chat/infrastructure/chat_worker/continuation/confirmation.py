"""Park a run at a durable offer, before any answer or optional tool is executed."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from service.services.chat.domain.confirmation.offer import create_confirmation_offer


async def anchor_pending_offer(redis: Any, request: Any, metadata: dict) -> dict:
    if not metadata.get("awaiting_confirmation") or metadata.get("mode_offer", {}).get("offer_id"):
        return metadata
    offer = dict(metadata["mode_offer"])
    anchor = await create_confirmation_offer(
        redis,
        thread_id=request.thread_id,
        user_id=str(request.user_id or ""),
        source_message_id=str(uuid5(NAMESPACE_URL, f"chat-offer:{request.job_id}")),
        text=request.text,
        selected_model=request.selected_model,
        route_override=request.route_override,
        resolved_category=(request.session_data or {}).get("_resolved_category"),
        input_type=request.input_type,
        attachments=request.attachments,
        file_ids=(request.session_data or {}).get("file_ids"),
        offer_mode=offer["mode"],
        offer_kind=offer.get("offer_kind", "mode"),
        continuation={
            "ide_context": (request.session_data or {}).get("_ide_context"),
            "document_context": {
                key: value
                for key, value in (
                    (request.session_data or {}).get("_document_context") or {}
                ).items()
                if key
                in {"path", "expected_revision", "authoring_version", "draft_digest", "block_ids"}
            }
            or None,
            "file_context": request.file_context,
            "web_search": request.web_search,
            "deep_research": request.deep_research,
            "planning": request.planning,
            "multi_intent": request.multi_intent,
            "memory_enabled": request.memory_enabled,
            "persona_ids": request.persona_ids,
        },
    )
    offer.update(
        offer_id=anchor.offer_id,
        status="pending",
        blocking=True,
        offered_at=datetime.now(UTC).isoformat(),
        expires_in_sec=30,
    )
    return {**metadata, "mode_offer": offer}
