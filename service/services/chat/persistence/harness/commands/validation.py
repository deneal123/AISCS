"""Known invalid arguments can retire only their exact uncreated exec intent."""

import json

from pydantic import ValidationError
from sqlalchemy import text

from service.services.chat.domain.ide.commands import CommandSpec
from service.services.chat.persistence.harness import effects
from service.services.chat.persistence.harness.state import owned_row, snapshot
from service.shared.harness_protocol import EffectResult, HarnessFailure
from service.shared.task_contract import digest_payload


async def reject_invalid(db, owner, operation_id, arguments):
    row = await owned_row(db, owner)
    current = await snapshot(db, row)
    record = (
        (
            await db.execute(
                text(
                    "SELECT intent,status,command FROM profile.harness_operation "
                    "WHERE task_id=:task AND operation_id=:operation FOR UPDATE"
                ),
                {"task": row["task_id"], "operation": operation_id},
            )
        )
        .mappings()
        .first()
    )
    if record is None or record["command"] is not None:
        raise HarnessFailure("operation_unknown")
    intent = record["intent"]
    if (
        intent["name"] != "ide_run_command"
        or intent["action"] != "exec"
        or digest_payload(json.loads(intent["arguments"])) != digest_payload(arguments)
    ):
        raise HarnessFailure("operation_conflict")
    try:
        CommandSpec.model_validate(arguments)
    except ValidationError:
        pass
    else:
        raise HarnessFailure("operation_conflict")
    # Exact current owner + locked absence of a CommandRecord prove the executor
    # could not have created/launched this operation. No success/evidence is minted.
    return await effects.record(
        db,
        row,
        EffectResult(
            operation_id=str(operation_id),
            status="failed",
            text="ide_command_arguments_rejected",
            charged=False,
        ),
        current,
        reconciled=True,
    )
