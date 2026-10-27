"""Durable effect identity and receipts, inside the task ownership transaction."""

import json
from uuid import UUID

from sqlalchemy import text

from service.services.chat.persistence.harness.state import require_known_cost
from service.shared.harness_protocol import EffectIntent, HarnessFailure
from service.shared.task_contract import digest_payload


async def read(db, row, operation_id):
    return (
        (
            await db.execute(
                text(
                    "SELECT intent,intent_digest,status,receipt FROM profile.harness_operation "
                    "WHERE task_id=:task_id AND operation_id=:operation_id FOR UPDATE"
                ),
                {"task_id": row["task_id"], "operation_id": UUID(operation_id)},
            )
        )
        .mappings()
        .first()
    )


async def prepare(db, row, intent, current):
    if current.state is None or intent.action not in current.state.contract.actions:
        raise HarnessFailure("task_permission_denied")
    existing = await read(db, row, intent.operation_id)
    digest = digest_payload(intent.model_dump(mode="json"))
    if existing:
        if existing["intent_digest"] != digest:
            raise HarnessFailure("operation_conflict")
        return {"status": existing["status"], "receipt": existing["receipt"]}
    if current.state.source_revision != intent.source_revision:
        raise HarnessFailure("binding_changed")
    uncertain = await db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM profile.harness_operation WHERE task_id=:task_id "
            "AND status IN ('dispatched','unknown') AND intent->>'action'<>'read')"
        ),
        {"task_id": row["task_id"]},
    )
    if uncertain:
        raise HarnessFailure("operation_unknown")
    await db.execute(
        text(
            "INSERT INTO profile.harness_operation(task_id,operation_id,intent,intent_digest) "
            "VALUES (:task_id,:operation_id,CAST(:body AS jsonb),:digest)"
        ),
        {
            "task_id": row["task_id"],
            "operation_id": UUID(intent.operation_id),
            "body": intent.model_dump_json(),
            "digest": digest,
        },
    )
    return {"status": "prepared", "receipt": None}


async def dispatch(db, row, operation_id):
    existing = await read(db, row, operation_id)
    if existing is None:
        raise HarnessFailure("operation_conflict")
    if existing["status"] != "prepared":
        return {"status": existing["status"], "dispatch_allowed": False}
    await require_known_cost(db, row["task_id"])
    # Recheck at dispatch: another prepared intent may have become uncertain
    # since this intent was admitted. The owning task row serializes this test.
    uncertain = await db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM profile.harness_operation WHERE task_id=:task_id "
            "AND status IN ('dispatched','unknown') AND intent->>'action'<>'read')"
        ),
        {"task_id": row["task_id"]},
    )
    if uncertain:
        raise HarnessFailure("operation_unknown")
    await db.execute(
        text(
            "UPDATE profile.harness_operation SET status='dispatched',updated_at=now() "
            "WHERE task_id=:task_id AND operation_id=:operation_id"
        ),
        {"task_id": row["task_id"], "operation_id": UUID(operation_id)},
    )
    return {"status": "dispatched", "dispatch_allowed": True}


async def record(db, row, receipt, current, *, reconciled=False):
    existing = await read(db, row, receipt.operation_id)
    if existing is None:
        raise HarnessFailure("operation_conflict")
    if any(proof.kind == "pdf" for proof in receipt.evidence) and (
        not reconciled
        or existing.get("intent", {}).get("name") in {"tex_propose_patch", "tex_propose_structure"}
    ):
        # Proposal ACK is not a compiler/artifact receipt. Even a syntactically
        # valid artifact_id supplied by an adapter cannot attest to a PDF build.
        raise HarnessFailure("verification_missing")
    if existing["receipt"] == receipt.model_dump(mode="json"):
        return {"status": existing["status"]}
    if (
        existing.get("intent", {}).get("name") == "ide_run_command"
        and not reconciled
        and receipt.status != "unknown"
    ):
        # Command completion belongs to the backend executor receipt, not an
        # adapter/model report. Its exact committed receipt may only be replayed.
        raise HarnessFailure("verification_missing")
    if existing["status"] != "dispatched" and not (reconciled and existing["status"] == "unknown"):
        raise HarnessFailure("operation_unknown")
    intent = EffectIntent.model_validate(existing["intent"])
    known = {item.criterion_id: item for item in current.state.contract.criteria}
    actions = {"read": "read", "file": "write", "command": "exec", "pdf": "document"}
    args = json.loads(intent.arguments)
    for proof in receipt.evidence:
        criterion = known.get(proof.criterion_id)
        if (
            receipt.status != "succeeded"
            or proof.outcome != "passed"
            or proof.operation_id != receipt.operation_id
            or criterion is None
            or criterion.kind != proof.kind
            or intent.action != actions[proof.kind]
            or proof.source_revision != intent.source_revision
            or (criterion.target and criterion.target != proof.target)
            or (proof.kind in {"read", "file"} and proof.target != args.get("path", ""))
        ):
            raise HarnessFailure("verification_missing")
    if receipt.status == "unknown" and receipt.evidence:
        raise HarnessFailure("verification_missing")
    await db.execute(
        text(
            "UPDATE profile.harness_operation SET status=:status,receipt=CAST(:body AS jsonb),"
            "updated_at=now() WHERE task_id=:task_id AND operation_id=:operation_id"
        ),
        {
            "task_id": row["task_id"],
            "operation_id": UUID(receipt.operation_id),
            "status": receipt.status,
            "body": receipt.model_dump_json(),
        },
    )
    return {"status": receipt.status}
