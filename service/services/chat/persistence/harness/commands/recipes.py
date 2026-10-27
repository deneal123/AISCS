"""Fix a criterion's check before dispatch; failed checks cannot be replaced by no-ops."""

import json

from sqlalchemy import text

from service.services.chat.domain.ide.verification import recipe
from service.services.chat.persistence.harness import effects
from service.services.chat.persistence.harness.commands.replay_guard import (
    require_observable_previous_commands,
)
from service.services.chat.persistence.harness.state import save_checkpoint
from service.shared.harness_protocol import EffectResult, HarnessFailure


async def bind_or_reject(db, row, current, spec, operation_id):
    """Called only after locked intent/spec equality and absence of a command.

    These validation refusals prove no command was created. Commit their receipt
    before returning the denial; unknown storage/dispatch outcomes are not covered.
    """
    try:
        await bind_recipe(db, row, current, spec)
    except HarnessFailure as failure:
        if failure.code not in {
            "task_permission_denied",
            "operation_conflict",
            "usage_limit_exceeded",
            "verification_unavailable",
        }:
            raise
        await effects.record(
            db,
            row,
            EffectResult(
                operation_id=str(operation_id),
                status="failed",
                text="ide_command_recipe_rejected",
                charged=False,
            ),
            current,
            reconciled=True,
        )
        return failure
    return None


async def bind_recipe(db, row, current, spec):
    await require_observable_previous_commands(db, row)
    if spec.criterion_id is None:
        return
    criteria = {item.criterion_id: item for item in current.state.contract.criteria}
    criterion = criteria.get(spec.criterion_id)
    if (
        criterion is None
        or criterion.kind != "command"
        or spec.profile == "shell"
        or (criterion.target and criterion.target != spec.target)
    ):
        raise HarnessFailure("task_permission_denied")
    saved = row.get("verification_recipes", {})
    candidate = recipe(spec)
    if spec.criterion_id in saved and saved[spec.criterion_id] != candidate:
        raise HarnessFailure("operation_conflict")
    previous = await db.scalar(
        text(
            "SELECT command FROM profile.harness_operation WHERE task_id=:task "
            "AND command->'spec'->>'criterion_id'=:criterion AND command IS NOT NULL "
            "ORDER BY updated_at DESC,operation_id DESC LIMIT 1"
        ),
        {"task": row["task_id"], "criterion": spec.criterion_id},
    )
    state = current.state
    if previous and (previous.get("verification") or {}).get("status") == "failed":
        if state.repairs >= state.contract.repair_limit:
            raise HarnessFailure("usage_limit_exceeded")
        state = state.advance(repairs=state.repairs + 1)
        await save_checkpoint(db, row, state=state, continuation=current.continuation)
    if spec.criterion_id not in saved:
        await db.execute(
            text(
                "UPDATE profile.harness_task SET verification_recipes=CAST(:body AS jsonb) "
                "WHERE task_id=:task"
            ),
            {"task": row["task_id"], "body": json.dumps({**saved, spec.criterion_id: candidate})},
        )
