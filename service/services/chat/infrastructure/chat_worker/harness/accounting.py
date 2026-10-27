"""Use durable paid-call receipts with the existing idempotent BillingService."""

import json
from uuid import UUID

from sqlalchemy import text

from service.services.billing.application.billing_service import BillingService
from service.services.billing.application.frozen_pricing import FrozenPricing
from service.services.billing.domain.charge_math import actually_charged
from service.services.billing.persistence.billing_repository import BillingRepository
from service.services.chat.application.harness_capability import settings
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.persistence.harness.fee_reconciliation import reconcile_tool_fees
from service.services.chat.persistence.harness.state import grant_rows


def enabled_for(result):
    config = settings()
    task = (result.get("metadata") or {}).get("task_result") or {}
    return config.ide_enabled or config.pdf_enabled or task.get("schema_version") == 2


async def charge_if_owned(pg_connector, config, *, result, user_id, job_id):
    """Keep durable uncertainty outside the legacy estimated-charge fallback."""
    if not user_id or not enabled_for(result):
        return None
    return await charge_harness(pg_connector, config, user_id=user_id, job_id=job_id)


async def _plan(db, user_id, job_id):
    row = (
        (
            await db.execute(
                text(
                    "SELECT t.*,j.payload AS job_payload FROM profile.harness_task t "
                    "JOIN profile.user_launch j ON j.id=t.active_job_id "
                    "WHERE t.active_job_id=:job AND t.user_id=:owner AND j.user_id=:owner "
                    "FOR UPDATE OF t"
                ),
                {"job": UUID(job_id), "owner": UUID(user_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    payload = row["job_payload"]
    if not any(key in payload for key in ("_accepted_turn_v1", "_prepared_turn_v1")):
        raise JobStateUnavailable("Harness settlement unavailable")
    # A latched terminal fences all future dispatch; never-dispatched allocations are free.
    await db.execute(
        text(
            "UPDATE profile.harness_grant SET state='waived' "
            "WHERE task_id=:id AND state='allocated'"
        ),
        {"id": row["task_id"]},
    )
    await reconcile_tool_fees(db, row["task_id"])
    grants = await grant_rows(db, row["task_id"])
    if any(grant["state"] in {"unknown", "dispatched"} for grant in grants):
        raise JobStateUnavailable("Harness cost reconciliation required")
    if row["settlement"] and row["settlement"]["job_id"] == job_id:
        return row["settlement"]
    calls, tools = [], []
    for grant in grants:
        if grant["state"] != "succeeded":
            continue
        request, receipt = grant["request"], grant["receipt"]
        if request.get("billing_tool"):
            tools.append(request["billing_tool"])
        else:
            calls.append(
                {**request, "prompt": receipt["prompt"], "completion": receipt["completion"]}
            )
    price = (
        FrozenPricing.model_validate(row["tariff"]).task_price(
            calls, tools, selected_model=row["admission"].get("pricing_model")
        )
        if calls or tools
        else None
    )
    cumulative = price.credits if price else 0
    if cumulative > row["admission"]["credit_limit"]:
        raise JobStateUnavailable("Harness budget reconciliation required")
    tokens = sum(call["prompt"] + call["completion"] for call in calls)
    previous = row["settlement"] or {}
    raw_cost = price.raw_cost_rub if price else 0
    from decimal import Decimal

    plan = {
        "task_id": str(row["task_id"]),
        "job_id": job_id,
        "cumulative": cumulative,
        "credits": max(0, cumulative - row["settled_credits"]),
        "reservation_id": row["admission"]["reservation_id"],
        "cumulative_tokens": tokens,
        "cumulative_raw_cost_rub": str(raw_cost),
        "tokens": max(0, tokens - previous.get("cumulative_tokens", 0)),
        "raw_cost_rub": str(
            max(
                Decimal(0),
                Decimal(raw_cost) - Decimal(previous.get("cumulative_raw_cost_rub", "0")),
            )
        ),
    }
    await db.execute(
        text("UPDATE profile.harness_task SET settlement=CAST(:plan AS jsonb) WHERE task_id=:id"),
        {"id": row["task_id"], "plan": json.dumps(plan)},
    )
    return plan


async def charge_harness(connector, config, *, user_id, job_id):
    try:
        async with connector.get_session_context() as db:
            plan = await _plan(db, user_id, job_id)
            await db.commit()  # Unknown ACK must not initiate another financial side effect.
        if plan is None:
            return None
        billing = BillingService(BillingRepository(connector), config.billing)
        result = await billing.charge(
            user_id,
            credits=plan["credits"],
            tokens=plan["tokens"],
            raw_cost_rub=float(plan["raw_cost_rub"]),
            reservation_id=plan["reservation_id"],
            idempotency_key=job_id,
            metadata={"harness_task_id": plan["task_id"]},
        )
        async with connector.get_session_context() as db:
            await db.execute(
                text(
                    "UPDATE profile.harness_task "
                    "SET settled_credits=GREATEST(settled_credits,:amount) "
                    "WHERE task_id=:id AND settlement->>'job_id'=:job"
                ),
                {"id": UUID(plan["task_id"]), "amount": plan["cumulative"], "job": job_id},
            )
            await db.commit()
        if result.get("idempotent"):
            return 0
        return actually_charged(result)
    except JobStateUnavailable:
        raise
    except Exception:
        raise JobStateUnavailable("Harness settlement unavailable") from None
