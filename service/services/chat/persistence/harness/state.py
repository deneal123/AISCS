"""Locked runtime state helpers shared by acknowledged exchanges and admission."""

import json

from sqlalchemy import text

from service.services.billing.application.frozen_pricing import FrozenPricing
from service.shared.harness_protocol import (
    Admission,
    Continuation,
    HarnessFailure,
    Snapshot,
)
from service.shared.task_contract import TaskState, digest_payload


async def require_known_cost(db, task_id):
    """An older grant cannot bypass a subsequently recorded unknown spend."""
    uncertain = await db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM profile.harness_grant "
            "WHERE task_id=:task_id AND state='unknown')"
        ),
        {"task_id": task_id},
    )
    if uncertain:
        raise HarnessFailure("cost_unknown")


async def owned_row(db, owner):
    row = (
        (
            await db.execute(
                text(
                    "SELECT t.*,j.status AS job_status,j.payload AS job_payload "
                    "FROM profile.harness_task t "
                    "JOIN profile.user_launch j ON j.id=t.active_job_id "
                    "JOIN profile.chat_threads c ON c.thread_id=t.thread_id "
                    "AND c.user_id=t.user_id "
                    "WHERE t.task_id=:task_id AND t.active_job_id=:job_id AND t.user_id=:user_id "
                    "AND t.thread_id=:thread_id AND t.execution_attempt_id=:attempt_id "
                    "AND t.fencing_epoch=:epoch AND j.user_id=t.user_id AND j.type='CHAT' "
                    "AND j.payload->>'thread_id'=CAST(CAST(:thread_id AS uuid) AS text) "
                    "AND j.payload->>'_execution_attempt_v1'="
                    "CAST(CAST(:attempt_id AS uuid) AS text) "
                    "FOR UPDATE OF t,j FOR SHARE OF c"
                ),
                owner.params(),
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["admission"] is None:
        raise HarnessFailure("harness_fenced")
    admission = Admission.model_validate(row["admission"])
    if admission.project_id != owner.project_id or admission.generation != owner.generation:
        raise HarnessFailure("binding_changed")
    return row


def stopped(row):
    payload = row["job_payload"]
    return payload.get("_cancel_requested_v1") is True


def require_active(row):
    if stopped(row):
        raise HarnessFailure("cancelled")
    recovery = row["job_payload"].get("_harness_transport_retry_v1") or {}
    if recovery.get("state") == "blocked" or (
        recovery.get("state") == "pending"
        and recovery.get("attempt_id") == str(row["execution_attempt_id"])
    ):
        raise HarnessFailure("harness_fenced")
    if row["job_status"] != "PROCESSING" or any(
        key in row["job_payload"]
        for key in ("_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1")
    ):
        raise HarnessFailure("harness_fenced")


async def grant_rows(db, task_id):
    return (
        (
            await db.execute(
                text(
                    "SELECT operation_id,request,request_digest,state,receipt "
                    "FROM profile.harness_grant "
                    "WHERE task_id=:task_id ORDER BY created_at,operation_id"
                ),
                {"task_id": task_id},
            )
        )
        .mappings()
        .all()
    )


def priced_totals(row, grants):
    tariff = FrozenPricing.model_validate(row["tariff"])
    actual, pending = [], []
    for grant in grants:
        request = grant["request"]
        if grant["state"] == "succeeded":
            receipt = grant["receipt"]
            actual.append(
                {**request, "prompt": receipt["prompt"], "completion": receipt["completion"]}
            )
        elif grant["state"] != "waived":
            pending.append(request)
    tools = [call["billing_tool"] for call in actual if call.get("billing_tool")]
    planned_tools = [call["billing_tool"] for call in pending if call.get("billing_tool")]
    selected = row["admission"].get("pricing_model")
    spent = tariff.task_price(actual, tools, selected_model=selected).credits if actual else 0
    total = (
        tariff.task_price(actual + pending, tools + planned_tools, selected_model=selected).credits
        if actual or pending
        else 0
    )
    return spent, max(0, total - spent)


async def snapshot(db, row):
    admission = Admission.model_validate(row["admission"])
    grants = await grant_rows(db, row["task_id"])
    spent, held = priced_totals(row, grants)
    state = TaskState.model_validate(row["checkpoint"]["state"]) if row["checkpoint"] else None
    if state is not None:
        raw = state.model_dump(mode="json")
        raw["budget"].update(spent_credits=spent, held_credits=held)
        state = TaskState.model_validate(raw)
    return Snapshot(
        admission=admission,
        revision=row["revision"],
        state=state,
        continuation=Continuation.model_validate(row["continuation"] or {}),
        spent_credits=spent,
        held_credits=held,
        stopped=stopped(row),
        settled_credits=row["settled_credits"],
        usage=[
            {
                "receipt_id": str(grant["operation_id"]),
                "provider": grant["request"]["provider"],
                "model": grant["request"]["model"],
                "kind": grant["request"]["kind"],
                "prompt": grant["receipt"]["prompt"],
                "completion": grant["receipt"]["completion"],
            }
            for grant in grants
            if grant["state"] == "succeeded" and not grant["request"].get("billing_tool")
        ],
    )


async def save_checkpoint(db, row, *, state, continuation):
    body = {
        "state": state.model_dump(mode="json"),
        "provider": continuation.provider.model_dump(mode="json")
        if continuation.provider
        else None,
    }
    await db.execute(
        text(
            "UPDATE profile.harness_task SET checkpoint=CAST(:body AS jsonb),"
            "checkpoint_digest=:digest,continuation=CAST(:continuation AS jsonb),"
            "revision=revision+1,updated_at=now() WHERE task_id=:task_id"
        ),
        {
            "task_id": row["task_id"],
            "body": json.dumps(body),
            "digest": digest_payload(body),
            "continuation": continuation.model_dump_json(),
        },
    )
