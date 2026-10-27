"""Serialized budget admission. Grants reserve cost; they never charge a user."""

import json
from uuid import UUID

from sqlalchemy import text

from service.services.chat.application.harness_capability import settings
from service.services.chat.persistence.harness.admission.calls import (
    precontract_limit_reached,
    stored_call,
)
from service.services.chat.persistence.harness.model_replay import completed_step_replay
from service.services.chat.persistence.harness.model_requests import (
    matching_request,
    require_frozen_request,
    require_unique_step,
)
from service.services.chat.persistence.harness.state import (
    grant_rows,
    priced_totals,
    require_known_cost,
)
from service.shared.harness_protocol import Admission, HarnessFailure
from service.shared.task_contract import digest_payload


async def _read(db, row, operation_id):
    return (
        (
            await db.execute(
                text(
                    "SELECT request,request_digest,state,receipt FROM profile.harness_grant "
                    "WHERE task_id=:task_id AND operation_id=:operation_id FOR UPDATE"
                ),
                {"task_id": row["task_id"], "operation_id": UUID(operation_id)},
            )
        )
        .mappings()
        .first()
    )


async def allocate(db, row, call):
    require_frozen_request(row, call)
    admission = Admission.model_validate(row["admission"])
    if call.prompt > admission.prompt_limit or call.completion > admission.completion_limit:
        raise HarnessFailure("budget_exhausted")
    existing = await _read(db, row, call.operation_id)
    if existing:
        if not matching_request(existing, call):
            raise HarnessFailure("operation_conflict")
        return {
            "status": existing["state"],
            "tariff_digest": digest_payload(row["tariff"]),
            "receipt": existing["receipt"] if existing["state"] == "succeeded" else None,
        }
    grants = list(await grant_rows(db, row["task_id"]))
    if replay := completed_step_replay(row, call, grants):
        return replay
    require_unique_step(call, grants)
    if precontract_limit_reached(row, call, grants):
        raise HarnessFailure("task_contract_invalid")
    model_calls = sum(not item["request"].get("billing_tool") for item in grants)
    if len(grants) >= 512 or (not call.billing_tool and model_calls >= admission.paid_call_limit):
        raise HarnessFailure("budget_exhausted")
    if any(item["state"] == "unknown" for item in grants):
        raise HarnessFailure("cost_unknown")
    stored = stored_call(row, call)
    candidate = {"request": stored, "state": "allocated"}
    spent, held = priced_totals(row, [*grants, candidate])
    if spent + held > admission.credit_limit:
        raise HarnessFailure("budget_exhausted")
    await db.execute(
        text(
            "INSERT INTO profile.harness_grant(task_id,operation_id,request,request_digest) "
            "VALUES (:task_id,:operation_id,CAST(:body AS jsonb),:digest)"
        ),
        {
            "task_id": row["task_id"],
            "operation_id": UUID(call.operation_id),
            "body": json.dumps(stored, ensure_ascii=False, sort_keys=True),
            "digest": digest_payload(call.model_dump(mode="json")),
        },
    )
    return {"status": "allocated", "tariff_digest": digest_payload(row["tariff"])}


async def dispatch(db, row, operation_id):
    if not settings().dispatch_enabled:
        raise HarnessFailure("dispatch_disabled")
    grant = await _read(db, row, operation_id)
    if grant is None:
        raise HarnessFailure("operation_conflict")
    if grant["state"] != "allocated":
        return {"status": grant["state"], "dispatch_allowed": False}
    await require_known_cost(db, row["task_id"])
    await db.execute(
        text(
            "UPDATE profile.harness_grant SET state='dispatched' "
            "WHERE task_id=:task_id AND operation_id=:operation_id"
        ),
        {"task_id": row["task_id"], "operation_id": UUID(operation_id)},
    )
    return {"status": "dispatched", "dispatch_allowed": True}


async def record(db, row, receipt):
    grant = await _read(db, row, receipt.operation_id)
    if grant is None:
        raise HarnessFailure("operation_conflict")
    raw = receipt.model_dump(mode="json")
    previous = grant["receipt"]
    if (
        isinstance(previous, dict)
        and {"provider_state": None, "finish_reason": None, **previous} == raw
    ):
        return {"status": grant["state"]}
    call = grant["request"]
    if receipt.provider_state is not None and (
        call.get("billing_tool")
        or receipt.provider_state.provider != call.get("provider")
        or receipt.provider_state.model != call.get("model")
    ):
        raise HarnessFailure("provider_state_incompatible")
    late_model_confirmation = (
        grant["state"] == "unknown"
        and not call.get("billing_tool")
        and receipt.status == "succeeded"
        and not receipt.estimated
    )
    if grant["state"] != "dispatched" and not late_model_confirmation:
        raise HarnessFailure("operation_unknown")
    if receipt.status == "waived" and not call.get("billing_tool"):
        raise HarnessFailure("usage_limit_exceeded")
    if (
        receipt.status == "succeeded"
        and not call.get("billing_tool")
        and (receipt.prompt + receipt.completion == 0 or receipt.message is None)
    ):
        raise HarnessFailure("usage_limit_exceeded")
    if receipt.prompt > call["prompt"] or receipt.completion > call["completion"]:
        raise HarnessFailure("usage_limit_exceeded")
    # Missing/estimated usage cannot release an uncertain cost reservation.
    status = "unknown" if receipt.estimated or receipt.status == "unknown" else receipt.status
    await db.execute(
        text(
            "UPDATE profile.harness_grant SET state=:state,receipt=CAST(:body AS jsonb) "
            "WHERE task_id=:task_id AND operation_id=:operation_id"
        ),
        {
            "task_id": row["task_id"],
            "operation_id": UUID(receipt.operation_id),
            "state": status,
            "body": receipt.model_dump_json(),
        },
    )
    return {"status": status}
