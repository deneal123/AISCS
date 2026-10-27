"""Recover only a local tool fee from its exact committed adapter receipt.

No provider spend, workspace state or model text is inferred here. The caller
holds the task row lock; this grants neither dispatch nor a new financial effect.
Legacy receipts without an explicit charge disposition remain unresolved.
"""

import json
from uuid import UUID, uuid5

from sqlalchemy import text

from service.shared.harness_protocol import CallReceipt, EffectIntent, EffectResult, PaidCall
from service.shared.task_contract import digest_payload


async def reconcile_tool_fees(db, task_id):
    rows = (
        (
            await db.execute(
                text(
                    "SELECT g.operation_id,g.request,e.intent,e.receipt "
                    "FROM profile.harness_grant g JOIN profile.harness_operation e "
                    "ON e.task_id=g.task_id AND e.intent_digest=g.request->>'request_digest' "
                    "WHERE g.task_id=:task AND g.state IN ('dispatched','unknown') "
                    "AND g.request->>'billing_tool'='workspace_tool' "
                    "AND e.status IN ('succeeded','failed') FOR UPDATE OF g"
                ),
                {"task": task_id},
            )
        )
        .mappings()
        .all()
    )
    resolved = 0
    for row in rows:
        intent = EffectIntent.model_validate(row["intent"])
        proof = EffectResult.model_validate(row["receipt"])
        fee = PaidCall.model_validate(row["request"])
        expected = PaidCall(
            operation_id=str(uuid5(UUID(intent.operation_id), "billing")),
            provider="local",
            model="workspace_tool",
            prompt=0,
            completion=0,
            request_digest=digest_payload(intent.model_dump(mode="json")),
            kind="tool",
            billing_tool="workspace_tool",
        )
        if (
            fee != expected
            or str(row["operation_id"]) != expected.operation_id
            or proof.operation_id != intent.operation_id
            or proof.status not in {"succeeded", "failed"}
            or proof.charged is None
        ):
            continue
        receipt = CallReceipt(
            operation_id=expected.operation_id,
            status="succeeded" if proof.charged else "waived",
        )
        await db.execute(
            text(
                "UPDATE profile.harness_grant SET state=:state,receipt=CAST(:receipt AS jsonb) "
                "WHERE task_id=:task AND operation_id=:operation "
                "AND state IN ('dispatched','unknown')"
            ),
            {
                "task": task_id,
                "operation": UUID(expected.operation_id),
                "state": receipt.status,
                "receipt": json.dumps(receipt.model_dump(mode="json")),
            },
        )
        resolved += 1
    return resolved
