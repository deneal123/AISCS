"""Fresh attempt transport; observed checkpoints are committed before terminal."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from service.services.chat.persistence.documents.audit.checkpoint import stage_checkpoint


def audit_failure_code(outcome: dict) -> str:
    if outcome.get("passed") is True:
        return "attestation_pending"
    return "audit_unavailable" if outcome.get("retryable") is True else "audit_failed"


async def invoke_fresh_audit(
    config: Any,
    session: Any,
    row: dict,
    ref: dict,
    attempt_id: UUID,
    audit: Callable[..., Awaitable[dict]],
    before_audit: Callable[[], Awaitable[None]] | None = None,
) -> dict:
    if before_audit is not None:
        await before_audit()

    async def persist(payload: dict) -> None:
        if before_audit is not None:
            await before_audit()
        await stage_checkpoint(session, row=row, payload=payload)
        await session.commit()

    return await audit(
        config,
        workspace_ref=ref,
        build_id=str(row["build_id"]),
        checkpoint_attempt_id=attempt_id,
        checkpoint_sink=persist,
        fresh_attempt=True,
    )
