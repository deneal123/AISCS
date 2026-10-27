"""Executor-only final evidence and source versions, committed with the receipt."""

from sqlalchemy import text

from service.services.chat.domain.ide.verification import recipe
from service.services.chat.persistence.harness import effects
from service.services.chat.persistence.harness.commands.evidence import latest_evidence
from service.services.chat.persistence.harness.state import save_checkpoint, snapshot
from service.shared.harness_protocol import EffectResult
from service.shared.task_contract import TaskEvidence, digest_payload


async def complete(db, row, command, files):
    current = await snapshot(db, row)
    state = current.state
    evidence = []
    checked = command.verification or {}
    if command.state != "completed" or checked.get("status") != "passed":
        for criterion in state.contract.criteria:
            if criterion.kind == "command" and criterion.criterion_id == command.spec.criterion_id:
                evidence.append(
                    TaskEvidence(
                        criterion_id=criterion.criterion_id,
                        operation_id=str(command.operation_id),
                        kind="command",
                        target=criterion.target,
                        source_revision=command.final_revision or state.source_revision,
                        digest=checked.get("recipe_digest") or digest_payload(recipe(command.spec)),
                        outcome="unknown" if checked.get("status") == "blocked" else "failed",
                        exit_code=command.result.exit_code if command.result else None,
                    )
                )
    if command.state == "completed" and checked.get("status") == "passed":
        for criterion in state.contract.criteria:
            if criterion.kind == "command" and criterion.criterion_id == command.spec.criterion_id:
                evidence.append(
                    TaskEvidence(
                        criterion_id=criterion.criterion_id,
                        operation_id=str(command.operation_id),
                        kind="command",
                        target=criterion.target,
                        source_revision=command.final_revision,
                        digest=checked["recipe_digest"],
                        outcome="passed",
                        exit_code=0,
                    )
                )
            prior = next(
                (
                    item
                    for item in reversed(state.evidence)
                    if item.criterion_id == criterion.criterion_id
                    and item.kind == "file"
                    and item.outcome == "passed"
                ),
                None,
            )
            actual = files.get(criterion.target)
            if criterion.kind == "file" and prior and actual == prior.digest:
                evidence.append(
                    TaskEvidence(
                        criterion_id=criterion.criterion_id,
                        operation_id=str(command.operation_id),
                        kind="file",
                        target=criterion.target,
                        source_revision=command.final_revision,
                        digest=actual,
                        outcome="passed",
                    )
                )
    receipt = EffectResult(
        operation_id=str(command.operation_id),
        status="succeeded" if command.state == "completed" else "failed",
        text="ide_command_" + command.state,
        evidence=evidence,
        charged=False,
    )
    # This branch alone can mint cross-kind command readback evidence. Public
    # effect_receipt rejects command success and cannot reach this authority.
    if evidence:
        existing = await effects.read(db, row, str(command.operation_id))
        if existing["status"] not in {"dispatched", "unknown"}:
            from service.shared.harness_protocol import HarnessFailure

            raise HarnessFailure("operation_unknown")
        await db.execute(
            text(
                "UPDATE profile.harness_operation SET status=:status,"
                "receipt=CAST(:body AS jsonb) "
                "WHERE task_id=:task AND operation_id=:operation"
            ),
            {
                "task": row["task_id"],
                "operation": command.operation_id,
                "body": receipt.model_dump_json(),
                "status": receipt.status,
            },
        )
    else:
        await effects.record(db, row, receipt, current, reconciled=True)
    if state is not None and (
        command.final_revision
        or evidence
        or command.failure_reason in {"source_revision_unavailable", "binding_changed"}
    ):
        updated = state.advance(
            source_revision=command.final_revision
            or (
                "unverified:" + str(command.operation_id)
                if command.failure_reason in {"source_revision_unavailable", "binding_changed"}
                else state.source_revision
            ),
            evidence=latest_evidence(state.evidence, evidence),
        )
        await save_checkpoint(db, row, state=updated, continuation=current.continuation)
