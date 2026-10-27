"""Read authoritative worker receipts without exposing prompts, tokens or IDs."""

import hashlib
import json

from sqlalchemy import text


async def read_balance(container, scope):
    from service.services.billing.application.billing_service import BillingService
    from service.services.billing.persistence.billing_repository import BillingRepository
    from service.settings import config

    billing = BillingService(BillingRepository(container.infra.pg_connector), config.billing)
    return (await billing.get_balance(str(scope.user_id))).total


async def evidence(container, scope, job):
    async with container.infra.pg_connector.get_session_context() as db:
        stored = (
            (
                await db.execute(
                    text("SELECT status,payload FROM profile.user_launch WHERE id=:job"),
                    {"job": job},
                )
            )
            .mappings()
            .one()
        )
        task = (
            (
                await db.execute(
                    text("SELECT * FROM profile.harness_task WHERE task_id=:job"), {"job": job}
                )
            )
            .mappings()
            .one()
        )
        reservation = (
            (
                await db.execute(
                    text(
                        "SELECT status,tokens_reserved FROM profile.token_reservations "
                        "WHERE harness_task_id=:job"
                    ),
                    {"job": job},
                )
            )
            .mappings()
            .one()
        )
        commands = (
            (
                await db.execute(
                    text(
                        "SELECT command FROM profile.harness_operation WHERE task_id=:job "
                        "AND command IS NOT NULL ORDER BY created_at"
                    ),
                    {"job": job},
                )
            )
            .scalars()
            .all()
        )
        events = (
            (
                await db.execute(
                    text("SELECT * FROM profile.billing_events WHERE user_id=:owner"),
                    {"owner": scope.user_id},
                )
            )
            .mappings()
            .all()
        )
        messages = await db.scalar(
            text(
                "SELECT count(*) FROM profile.chat_messages WHERE thread_id IN "
                "(SELECT id FROM profile.chat_threads WHERE thread_id=:thread)"
            ),
            {"thread": scope.thread_id},
        )
        grants = (
            (
                await db.execute(
                    text(
                        "SELECT state,request,receipt FROM profile.harness_grant "
                        "WHERE task_id=:job ORDER BY created_at"
                    ),
                    {"job": job},
                )
            )
            .mappings()
            .all()
        )
    balance = await read_balance(container, scope)
    result = stored["payload"].get("metadata", {}).get("task_result")
    assert stored["status"] == "SUCCESS" and result and result["status"] == "completed", (
        "acceptance_worker_incomplete"
    )
    assert result["verified"] and not result["unchecked"]
    assert set(result["confirmed"]) == {"script", "verify_project"}
    assert len(commands) == 1 and commands[0]["cleanup_confirmed"]
    assert commands[0]["verification"]["status"] == "passed"
    assert commands[0]["result"]["stdout"] == "hello world\n"
    assert commands[0]["final_revision"] == task["checkpoint"]["state"]["source_revision"]
    assert (
        task["settled_credits"] > 0 and task["settlement"]["cumulative"] == task["settled_credits"]
    )
    assert len(events) == 1 and messages == 2
    assert all(item["state"] in {"succeeded", "waived"} for item in grants)
    assert reservation["status"] == "committed"
    return {
        "digest": hashlib.sha256(
            json.dumps(
                {
                    "job": dict(stored),
                    "task": dict(task),
                    "events": [dict(item) for item in events],
                    "grants": [dict(item) for item in grants],
                    "reservation": dict(reservation),
                    "balance": balance,
                    "messages": messages,
                },
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest(),
        "spent": task["settled_credits"],
        "balance": balance,
        "commands": len(commands),
    }
