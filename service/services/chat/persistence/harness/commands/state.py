"""Closed command transitions; no model text can advance executor state."""

from sqlalchemy import text

from service.services.chat.domain.ide.commands import CommandRecord
from service.shared.harness_protocol import HarnessFailure

TRANSITIONS = {
    "preparing": {"ready", "unknown", "cancelled", "failed"},
    "ready": {"dispatching", "unknown", "cancelled", "failed", "stopping"},
    "dispatching": {"running", "unknown", "stopping", "cancelled"},
    "running": {"completed", "failed", "stopping", "unknown", "cancelled"},
    "stopping": {"cancelled", "unknown", "failed"},
    "unknown": {"running", "stopping", "completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


async def read(db, task_id, operation_id):
    raw = await db.scalar(
        text(
            "SELECT command FROM profile.harness_operation "
            "WHERE task_id=:task AND operation_id=:operation FOR UPDATE"
        ),
        {"task": task_id, "operation": operation_id},
    )
    if raw is None:
        raise HarnessFailure("operation_conflict")
    return CommandRecord.model_validate(raw)


async def save(db, old, new):
    if old == new:
        return
    immutable = (
        "operation_id",
        "task_id",
        "repository_id",
        "workspace_id",
        "generation",
        "attempt_id",
        "epoch",
        "deadline_at",
        "spec",
    )
    if any(getattr(old, key) != getattr(new, key) for key in immutable):
        raise HarnessFailure("operation_conflict")
    if new.state not in TRANSITIONS[old.state] and not (
        new.state == old.state and old.state not in {"completed", "failed", "cancelled"}
    ):
        raise HarnessFailure("operation_unknown")
    for key in (
        "snapshot_id",
        "snapshot_digest",
        "source_revision",
        "engine_id",
        "container_id",
        "supervisor",
        "stop_reason",
    ):
        if getattr(old, key) is not None and getattr(old, key) != getattr(new, key):
            raise HarnessFailure("operation_conflict")
    for key in ("cleanup_confirmed", "output_complete", "dispatch_authorized"):
        if getattr(old, key) and not getattr(new, key):
            raise HarnessFailure("operation_conflict")
    phases = {
        "unclaimed": {"creating"},
        "creating": {"created", "unknown"},
        "created": {"handshaking", "unknown"},
        "handshaking": {"waiting", "unknown"},
        "waiting": {"sent", "unknown"},
        "sent": {"unknown"},
        "unknown": set(),
    }
    if new.engine_phase != old.engine_phase and new.engine_phase not in phases[old.engine_phase]:
        raise HarnessFailure("operation_unknown")
    if new.state == "cancelled" and old.engine_id and not new.cleanup_confirmed:
        raise HarnessFailure("operation_unknown")
    await db.execute(
        text(
            "UPDATE profile.harness_operation SET command=CAST(:body AS jsonb),"
            "command_state=:state,updated_at=now() WHERE task_id=:task AND operation_id=:operation"
        ),
        {
            "body": new.model_dump_json(),
            "state": new.state,
            "task": new.task_id,
            "operation": new.operation_id,
        },
    )
