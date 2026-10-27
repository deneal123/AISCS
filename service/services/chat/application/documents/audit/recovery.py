"""Import a sealed producer outcome into the owned audit settlement seam."""

from typing import Any
from uuid import UUID

from service.infrastructure.agents_client.document_audit.recovery import recover_document_audit
from service.services.chat.persistence.documents.audit.attempts import (
    RecordedAuditResult,
    lock_started,
    record_merged_result,
)
from service.services.chat.persistence.documents.audit.checkpoint import stage_checkpoint


async def recover_started_result(
    *,
    config: Any,
    session: Any,
    row: dict,
    ref: dict,
    attempt_id: UUID,
) -> RecordedAuditResult | None:
    if not await lock_started(session, row, attempt_id=attempt_id):
        return None
    await session.commit()  # Never keep the row lock while reading the remote registry.
    snapshot = await recover_document_audit(
        config,
        workspace_ref=ref,
        build_id=str(row["build_id"]),
        attempt_id=attempt_id,
    )
    if snapshot.state != "terminal" or snapshot.outcome is None:
        return None  # Active/unknown state does not authorize another call or settlement.
    if not await lock_started(session, row, attempt_id=attempt_id):
        return None
    if snapshot.checkpoint is not None:
        await stage_checkpoint(session, row=row, payload=snapshot.checkpoint)
        await session.commit()
    outcome = snapshot.outcome
    failure = (
        "attestation_pending"
        if outcome["passed"]
        else ("audit_unavailable" if outcome["retryable"] else "audit_failed")
    )
    # Terminal usage comes from the preserved canonical checkpoint, not a mutable
    # remote total; result merge cannot erase an already stored receipt.
    recorded = await record_merged_result(
        session, attempt_id=attempt_id, usage={}, failure_code=failure
    )
    if recorded is not None:
        await session.commit()
    return recorded
