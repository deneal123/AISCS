"""One backend-owned completion projection for transport and cancelled settlement."""

from sqlalchemy import text

from service.shared.task_contract import CompletionVerifier


def task_result(current, pending=False):
    if current.state is None:
        return None
    state = current.state.advance(cancelled=True) if current.stopped else current.state
    result = CompletionVerifier.evaluate(state, pending_operations=bool(pending))
    if (
        result["status"] == "partial"
        and any(
            criterion.kind in {"command", "pdf"} and criterion.criterion_id in result["unchecked"]
            for criterion in state.contract.criteria
        )
        and not pending
        and not current.held_credits
    ):
        result.update(status="blocked", blocker="verification_unavailable")
    return result


async def read_result(db, row, current):
    pending = await db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM profile.harness_operation WHERE task_id=:task_id "
            "AND status IN ('prepared','dispatched','unknown')) OR "
            "EXISTS(SELECT 1 FROM profile.harness_grant WHERE task_id=:task_id "
            "AND state IN ('allocated','dispatched','unknown'))"
        ),
        {"task_id": row["task_id"]},
    )
    result = task_result(current, pending)
    recovery = (row.get("job_payload") or {}).get("_harness_transport_retry_v1") or {}
    if result and result["status"] != "cancelled" and recovery.get("state") == "blocked":
        reason = result["blocker"]
        result.update(
            status="blocked",
            verified=False,
            blocker=reason
            if reason in {"cost_unknown", "operation_unknown"}
            else "checkpoint_unavailable",
        )
    from service.services.chat.persistence.harness.refinement import adopt_verified_refinement

    await adopt_verified_refinement(db, row, current, result)
    return result
