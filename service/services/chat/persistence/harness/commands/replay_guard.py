"""Новый operation ID не даёт разрешения повторять код после невосстановимого вывода."""

from sqlalchemy import text

from service.shared.harness_protocol import HarnessFailure


async def require_observable_previous_commands(db, row):
    blocked = await db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM profile.harness_operation WHERE task_id=:task "
            "AND command IS NOT NULL AND command_state IN ('failed','cancelled') "
            "AND (command->'verification'->>'status'='blocked' "
            "OR command->>'failure_reason' IN "
            "('output_unavailable','source_revision_unavailable','binding_changed')))"
        ),
        {"task": row["task_id"]},
    )
    if blocked is True:
        raise HarnessFailure("verification_unavailable")
