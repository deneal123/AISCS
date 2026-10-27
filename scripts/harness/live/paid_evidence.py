"""Independent checks of the actual paid task, not model prose or fixture usage."""

import hashlib
import json

from sqlalchemy import text

from scripts.harness.live.paid_setup import paid_model
from scripts.harness.live.worker_assertions import read_balance
from service.services.chat.persistence.harness.state import priced_totals


def assert_model_binding(grants, model):
    inference = [grant for grant in grants if not grant["request"].get("billing_tool")]
    assert inference and all(
        grant["request"]["model"] == model and grant["request"]["provider"] == "gigachat"
        for grant in inference
    )
    for grant in grants:
        request = grant["request"]
        if request.get("billing_tool"):
            assert request["kind"] == "tool" and request["provider"] == "local"
            assert request["model"] == request["billing_tool"] == "workspace_tool"


async def evidence(container, scope, job):
    async with container.infra.pg_connector.get_session_context() as db:
        task = (
            (
                await db.execute(
                    text("SELECT * FROM profile.harness_task WHERE task_id=:job"), {"job": job}
                )
            )
            .mappings()
            .one()
        )
        launch = (
            (
                await db.execute(
                    text("SELECT status,payload FROM profile.user_launch WHERE id=:job"),
                    {"job": job},
                )
            )
            .mappings()
            .one()
        )
        operations = (
            (
                await db.execute(
                    text(
                        "SELECT * FROM profile.harness_operation "
                        "WHERE task_id=:job ORDER BY operation_id"
                    ),
                    {"job": job},
                )
            )
            .mappings()
            .all()
        )
        grants = (
            (
                await db.execute(
                    text(
                        "SELECT * FROM profile.harness_grant "
                        "WHERE task_id=:job ORDER BY operation_id"
                    ),
                    {"job": job},
                )
            )
            .mappings()
            .all()
        )
        events = (
            (
                await db.execute(
                    text(
                        "SELECT * FROM profile.billing_events WHERE user_id=:owner "
                        "AND metadata->>'harness_task_id'=:job"
                    ),
                    {"owner": scope.user_id, "job": str(job)},
                )
            )
            .mappings()
            .all()
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
        pins = await db.scalar(
            text(
                "SELECT sum(command_pins) FROM profile.ide_checkpoint_intent "
                "WHERE repository_id=:project"
            ),
            {"project": scope.repository_id},
        )
    result = (launch["payload"].get("metadata") or {}).get("task_result") or {}
    assert launch["status"] == "SUCCESS" and result.get("status") == "completed", (
        "paid_task_incomplete"
    )
    assert result["verified"] and not result["unchecked"]
    state = task["checkpoint"]["state"]
    assert 0 < state["rounds"] <= 16 and state["repairs"] <= 2
    spent, held = priced_totals(task, grants)
    assert held == 0 and 0 < task["settled_credits"] <= reservation["tokens_reserved"]
    assert spent == task["settled_credits"]
    assert reservation["status"] == "committed" and pins == 0
    assert operations and all(
        op["status"] in {"succeeded", "failed", "conflict"} for op in operations
    )
    assert grants and all(grant["state"] in {"succeeded", "waived"} for grant in grants)
    assert_model_binding(grants, paid_model())
    commands = [op["command"] for op in operations if op["command"] is not None]
    assert commands and all(command["cleanup_confirmed"] for command in commands)
    passed = [
        command
        for command in commands
        if command["state"] == "completed" and command["verification"]["status"] == "passed"
    ]
    assert any(
        command["spec"]["profile"] == "python_script"
        and command["spec"]["target"] == "hello_world.py"
        and command["result"]["stdout"] == "hello world\n"
        and command["result"]["exit_code"] == 0
        and command["final_revision"] == state["source_revision"]
        for command in passed
    )
    assert len(events) == 1 and events[0]["metadata"]["idempotency_key"] == str(job)
    assert task["settlement"]["cumulative"] == task["settled_credits"]
    tokens = sum(
        (grant["receipt"] or {}).get("prompt", 0) + (grant["receipt"] or {}).get("completion", 0)
        for grant in grants
    )
    assert tokens > 0
    assert events[0]["event_type"] == "usage" and events[0]["tokens"] == tokens
    assert events[0]["metadata"]["credits"] == task["settled_credits"]
    from service.composition.ide import build_ide_runtime

    runtime = build_ide_runtime(container.infra.pg_connector)
    binding = (await runtime.resolve(scope)).binding
    actual = await runtime.client.read(
        scope.user_id, binding, operation="file", path="hello_world.py"
    )
    assert actual["content"]
    assert any(
        item["kind"] == "file"
        and item["target"] == "hello_world.py"
        and item["outcome"] == "passed"
        and item["digest"] == actual["digest"]
        and item["source_revision"] == state["source_revision"]
        for item in state["evidence"]
    )
    public = json.dumps(launch["payload"])
    for command in commands:
        assert command["engine_id"] not in public and command["container_id"] not in public
    balance = await read_balance(container, scope)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "task": dict(task),
                "launch": dict(launch),
                "operations": [dict(op) for op in operations],
                "grants": [dict(grant) for grant in grants],
                "events": [dict(event) for event in events],
                "balance": balance,
                "reservation": dict(reservation),
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    return {
        "digest": fingerprint,
        "balance": balance,
        "credits": task["settled_credits"],
        "tokens": tokens,
        "rounds": state["rounds"],
        "commands": len(commands),
        "reserved": reservation["tokens_reserved"],
    }
