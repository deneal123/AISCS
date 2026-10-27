"""Private frames are validated and persisted before accepting audit completion."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID

from service.infrastructure.agents_client.contracts.protocol_manifest import load_protocol_manifest
from service.infrastructure.sidecar import SidecarUnavailable
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import UsageJournal

CHECKPOINT_KEY = load_protocol_manifest().usage_checkpoint_key
RESULT_KEY = "__audit_result__"
AUDIT_PROTOCOL_PATH = "/document-audit/v2"


async def consume_audit_frames(
    frames: AsyncIterator[dict],
    *,
    attempt_id: UUID,
    persist: Callable[[dict], Awaitable[None]],
) -> dict:
    """`persist` must return only after commit; a failed commit never becomes an ACK.

    Do not retry model operations. This consumer does not prove the producer has
    stopped after an arbitrary connection loss; caller owns that recovery seam.
    """
    previous: UsageJournal | None = None
    result: dict | None = None
    async for frame in frames:
        if result is not None or len(frame) != 1:
            raise SidecarUnavailable("agents", "protocol")
        if CHECKPOINT_KEY in frame:
            try:
                journal = UsageJournal.decode(frame[CHECKPOINT_KEY])
                if journal.attempt_id != str(attempt_id):
                    raise ValueError
                if any(item.kind != "document_visual_audit" for item in journal.receipts):
                    raise ValueError
                if previous is not None and journal != previous and not journal.extends(previous):
                    raise ValueError
            except Exception:
                raise SidecarUnavailable("agents", "protocol") from None
            await persist(journal.payload())
            previous = journal
        elif RESULT_KEY in frame and isinstance(frame[RESULT_KEY], dict):
            result = frame[RESULT_KEY]
        else:
            raise SidecarUnavailable("agents", "protocol")
    if result is None:
        raise SidecarUnavailable("agents", "protocol")
    return result
