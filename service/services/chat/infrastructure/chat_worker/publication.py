"""Post-commit publication for a durable chat turn."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from service.services.chat.infrastructure.chat_worker.phases import RunPhase, RunPhaseState

logger = logging.getLogger(__name__)

MemoryExtractor = Callable[..., Awaitable[None]]


async def publish_committed_turn(
    *,
    publisher: Any,
    job_id: str,
    reply: str,
    file_url: str | None,
    metadata: dict[str, Any],
    run_phase: RunPhaseState,
    memory_enabled: bool,
    extract_memory: MemoryExtractor,
    memory_kwargs: dict[str, Any],
) -> None:
    """Publish a committed result and perform best-effort memory maintenance.

    Failure here must never refund or relabel a turn that PostgreSQL has already
    committed as successful.  ``published`` represents completion of this
    best-effort stage; the transport outcome remains available on ``run_phase``.
    """

    try:
        delivered = publisher.publish_payload(
            {
                "type": "agent_reply",
                "job_id": job_id,
                "reply": reply,
                "file_url": file_url,
                "metadata": metadata,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        run_phase.mark_publication(delivered)
        if memory_enabled:
            await extract_memory(**memory_kwargs)
    except Exception:
        if run_phase.phase is RunPhase.PERSISTED:
            run_phase.mark_publication(False)
        logger.warning(
            "post-commit publish/memory failed",
            extra={"component": "chat_worker", "failure_code": "post_commit"},
        )
    run_phase.advance(RunPhase.FINALIZED)


__all__ = ["publish_committed_turn"]
