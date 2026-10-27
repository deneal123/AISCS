"""Проверяемые подтверждения вопроса и продолжения, без публикации приватных данных."""

import hashlib
import json

from sqlalchemy import text

from scripts.harness.live.worker_assertions import read_balance


async def model_call_count(container, task):
    async with container.infra.pg_connector.get_session_context() as db:
        return await db.scalar(
            text(
                "SELECT count(*) FROM profile.harness_grant WHERE task_id=:task "
                "AND request->>'billing_tool' IS NULL AND state='succeeded'"
            ),
            {"task": task},
        )


async def job_row(container, job):
    async with container.infra.pg_connector.get_session_context() as db:
        return (
            (
                await db.execute(
                    text("SELECT status,payload FROM profile.user_launch WHERE id=:job"),
                    {"job": job},
                )
            )
            .mappings()
            .one()
        )


async def pause_evidence(container, scope, root):
    stored = await job_row(container, root)
    metadata = stored["payload"]["metadata"]
    assert stored["status"] == "SUCCESS"
    assert metadata["task_result"]["status"] == "waiting_user"
    question = metadata["human_question"]
    assert question["state"] == "pending" and question["resume_job_id"] is None
    async with container.infra.pg_connector.get_session_context() as db:
        task = (
            (
                await db.execute(
                    text("SELECT * FROM profile.harness_task WHERE task_id=:root"), {"root": root}
                )
            )
            .mappings()
            .one()
        )
        assert task["checkpoint"] is None and task["continuation"]["phase"] == "admitting"
        assert task["active_job_id"] == root and task["settled_credits"] > 0
        assert (
            await db.scalar(
                text("SELECT count(*) FROM profile.harness_operation WHERE task_id=:root"),
                {"root": root},
            )
            == 0
        )
    assert "continuation" not in json.dumps(question) and "capability" not in json.dumps(metadata)
    return question, task["settled_credits"]


async def final_evidence(container, scope, root, child, goal):
    stored = await job_row(container, child)
    result = stored["payload"].get("metadata", {}).get("task_result") or {}
    assert stored["status"] == "SUCCESS" and result.get("status") == "completed", (
        "acceptance_question_child_incomplete"
    )
    assert result["verified"] and set(result["confirmed"]) == {"script", "verify_project"}
    assert not result["unchecked"] and result["rounds"] == 5
    async with container.infra.pg_connector.get_session_context() as db:
        task = (
            (
                await db.execute(
                    text("SELECT * FROM profile.harness_task WHERE task_id=:root"), {"root": root}
                )
            )
            .mappings()
            .one()
        )
        commands = (
            (
                await db.execute(
                    text(
                        "SELECT command FROM profile.harness_operation "
                        "WHERE task_id=:root AND command IS NOT NULL"
                    ),
                    {"root": root},
                )
            )
            .scalars()
            .all()
        )
        grants = (
            (
                await db.execute(
                    text(
                        "SELECT state,request,receipt FROM profile.harness_grant "
                        "WHERE task_id=:root ORDER BY created_at,operation_id"
                    ),
                    {"root": root},
                )
            )
            .mappings()
            .all()
        )
        reservations = (
            (
                await db.execute(
                    text(
                        "SELECT status,tokens_reserved FROM profile.token_reservations "
                        "WHERE harness_task_id=:root ORDER BY reservation_id"
                    ),
                    {"root": root},
                )
            )
            .mappings()
            .all()
        )
        events = (
            (
                await db.execute(
                    text("SELECT * FROM profile.billing_events WHERE user_id=:owner ORDER BY id"),
                    {"owner": scope.user_id},
                )
            )
            .mappings()
            .all()
        )
        assert (
            await db.scalar(
                text("SELECT count(*) FROM profile.human_question WHERE source_job_id=:root"),
                {"root": root},
            )
            == 1
        )
    assert task["active_job_id"] == child and task["fencing_epoch"] > 1
    state = task["checkpoint"]["state"]
    assert state["contract"]["goal"] == goal and state["rounds"] == 5
    assert task["continuation"]["provider"]["provider"] == "gigachat"
    assert json.loads(task["continuation"]["clarification"])["answer"]["text"] == "hello_world.py"
    assert len(commands) == 1 and commands[0]["cleanup_confirmed"]
    assert commands[0]["result"]["stdout"] == "hello world\n"
    assert commands[0]["verification"]["status"] == "passed"
    assert commands[0]["final_revision"] == state["source_revision"]
    assert all(item["state"] in {"succeeded", "waived"} for item in grants)
    model_calls = len([item for item in grants if not item["request"].get("billing_tool")])
    assert len(events) == 2 and len(reservations) == 2
    assert all(item["status"] == "committed" for item in reservations)
    balance = await read_balance(container, scope)
    digest = hashlib.sha256(
        json.dumps(
            {
                "job": dict(stored),
                "task": dict(task),
                "commands": commands,
                "grants": [dict(item) for item in grants],
                "events": [dict(item) for item in events],
                "reservations": [dict(item) for item in reservations],
                "balance": balance,
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    return {
        "digest": digest,
        "balance": balance,
        "spent": task["settled_credits"],
        "model_calls": model_calls,
    }
