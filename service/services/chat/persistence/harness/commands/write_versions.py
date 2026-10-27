"""A confirmed write invalidates prior checks, even before another command runs."""

from sqlalchemy import text

from service.services.chat.persistence.harness import effects
from service.services.chat.persistence.harness.commands.evidence import latest_evidence
from service.services.chat.persistence.harness.commands.read_versions import record_read_evidence
from service.services.chat.persistence.harness.state import save_checkpoint
from service.shared.harness_protocol import HarnessFailure


async def accept_effect(db, row, receipt, current):
    existing = await effects.read(db, row, receipt.operation_id)
    is_write = (
        current.admission.surface == "ide"
        and existing is not None
        and existing["intent"]["action"] == "write"
        and receipt.status == "succeeded"
    )
    if not is_write:
        operation = await effects.record(db, row, receipt, current)
        await record_read_evidence(db, row, receipt, current)
        return operation
    revision = "write:" + receipt.operation_id
    proofs = [item.model_copy(update={"source_revision": revision}) for item in receipt.evidence]
    normalized = receipt.model_copy(update={"evidence": tuple(proofs)})
    if existing["receipt"] == normalized.model_dump(mode="json"):
        return {"status": existing["status"]}
    # Validate the original adapter receipt before deriving a backend version.
    await effects.record(db, row, receipt, current)
    await db.execute(
        text(
            "UPDATE profile.harness_operation SET receipt=CAST(:body AS jsonb) "
            "WHERE task_id=:task AND operation_id=CAST(:operation AS uuid)"
        ),
        {
            "body": normalized.model_dump_json(),
            "task": row["task_id"],
            "operation": receipt.operation_id,
        },
    )
    if current.state is None:
        raise HarnessFailure("task_contract_missing")
    state = current.state.advance(
        source_revision=revision, evidence=latest_evidence(current.state.evidence, proofs)
    )
    await save_checkpoint(db, row, state=state, continuation=current.continuation)
    return {"status": "succeeded"}
