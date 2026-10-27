"""Два настоящих worker-задания: второй использует урок, не повторяя улучшатель."""

import asyncio
import json
import logging
import sys
import traceback
from uuid import uuid4

from sqlalchemy import text

from scripts.harness.live.environment import backend_http, environment
from scripts.harness.live.refinement import assert_adopted
from scripts.harness.live.worker_assertions import read_balance
from scripts.harness.live.worker_process import deliver, prefork_worker
from scripts.harness.live.worker_setup import funded_job

QUESTION = "Прочитай hello_world.py и объясни его содержимое. Ничего не меняй и не запускай."
STAGE = "lesson_reuse_environment"
logging.disable(logging.CRITICAL)


async def facts(container, scope, job):
    async with container.infra.pg_connector.get_session_context() as db:
        task = (
            (
                await db.execute(
                    text(
                        "SELECT j.status,j.payload,t.checkpoint,t.continuation,t.settled_credits "
                        "FROM profile.user_launch j JOIN profile.harness_task t ON t.task_id=j.id "
                        "WHERE j.id=:job"
                    ),
                    {"job": job},
                )
            )
            .mappings()
            .one()
        )
        grants = (
            (
                await db.execute(
                    text(
                        "SELECT operation_id,state,request,receipt FROM profile.harness_grant "
                        "WHERE task_id=:job ORDER BY created_at,operation_id"
                    ),
                    {"job": job},
                )
            )
            .mappings()
            .all()
        )
        operations = (
            (
                await db.execute(
                    text(
                        "SELECT operation_id,status,intent->>'name' AS name "
                        "FROM profile.harness_operation WHERE task_id=:job "
                        "ORDER BY created_at,operation_id"
                    ),
                    {"job": job},
                )
            )
            .mappings()
            .all()
        )
        charges = await db.scalar(
            text("SELECT count(*) FROM profile.billing_events WHERE user_id=:owner"),
            {"owner": scope.user_id},
        )
    result = task["payload"]["metadata"]["task_result"]
    assert task["status"] == "SUCCESS" and result["status"] == "completed" and result["verified"]
    assert result["confirmed"] == ["source"] and not result["unchecked"]
    assert all(grant["state"] == "succeeded" for grant in grants)
    assert len(operations) == 1 and operations[0]["name"] == "ide_read_file"
    assert operations[0]["status"] == "succeeded" and task["settled_credits"] > 0
    return {
        "task": dict(task),
        "grants": [dict(row) for row in grants],
        "operations": [dict(row) for row in operations],
        "charges": charges,
    }


async def next_job(container, scope, previous):
    job = uuid4()
    async with container.infra.pg_connector.get_session_context() as db:
        await db.execute(
            text(
                "INSERT INTO profile.user_launch(id,user_id,type,status,payload) "
                "VALUES (:job,:owner,'CHAT','NEW',CAST(:body AS jsonb))"
            ),
            {
                "job": job,
                "owner": scope.user_id,
                "body": json.dumps({"thread_id": str(scope.thread_id), "text": QUESTION}),
            },
        )
        await db.commit()
    return job, {**previous, "job_id": str(job)}


async def exercise(container):
    global STAGE
    from service.composition.ide import build_ide_runtime
    from service.settings import config

    scope, first_job, initial_balance, first_kwargs = await funded_job(
        container, question=QUESTION, create_file=True
    )
    queue = "harness-" + uuid4().hex
    async with prefork_worker(config.pg.db, queue) as (app, first_pid):
        STAGE = "lesson_reuse_first_delivery"
        result = await deliver(app, queue, first_kwargs)
        assert result["status"] == "success"
        first = await facts(container, scope, first_job)
        assert first["task"]["checkpoint"]["state"]["protocol_repairs"] == 1
        await assert_adopted(container, first_job, terminal=True)
        second_job, second_kwargs = await next_job(container, scope, first_kwargs)
        STAGE = "lesson_reuse_second_delivery"
        result = await deliver(app, queue, second_kwargs)
        assert result["status"] == "success"
        second = await facts(container, scope, second_job)
        STAGE = "lesson_reuse_verify_no_new_refinement"
        state, continuation = second["task"]["checkpoint"]["state"], second["task"]["continuation"]
        if state["protocol_repairs"] or continuation.get("refinement"):
            print(
                json.dumps(
                    {
                        "stage": STAGE,
                        "second_protocol_repairs": state["protocol_repairs"],
                        "second_has_refinement": bool(continuation.get("refinement")),
                    }
                ),
                flush=True,
            )
        assert state["protocol_repairs"] == 0 and not continuation.get("refinement")
        assert len(second["grants"]) < len(first["grants"])
        assert second["charges"] == 2
        spent = first["task"]["settled_credits"] + second["task"]["settled_credits"]
        assert initial_balance - await read_balance(container, scope) == spent
        first = await facts(container, scope, first_job)
        STAGE = "lesson_reuse_duplicate_delivery"
        for job, kwargs, saved in (
            (first_job, first_kwargs, first),
            (second_job, second_kwargs, second),
        ):
            assert (await deliver(app, queue, kwargs))["status"] == "success"
            assert await facts(container, scope, job) == saved
    STAGE = "lesson_reuse_restart_delivery"
    async with prefork_worker(config.pg.db, queue) as (app, second_pid):
        assert second_pid != first_pid
        for job, kwargs, saved in (
            (first_job, first_kwargs, first),
            (second_job, second_kwargs, second),
        ):
            assert (await deliver(app, queue, kwargs))["status"] == "success"
            assert await facts(container, scope, job) == saved
    runtime = build_ide_runtime(container.infra.pg_connector)
    resolved = await runtime.resolve(scope)
    actual = await runtime.client.read(
        scope.user_id, resolved.binding, operation="file", path="hello_world.py"
    )
    assert actual["content"] == "print('hello world')\n"
    assert initial_balance - await read_balance(container, scope) == spent
    return {
        "lesson_reuse_verified": True,
        "skipped_new_refinement": True,
        "mutations": 0,
        "commands": 0,
        "charges": 2,
        "replay_unchanged": True,
        "restart_replay_unchanged": True,
    }


async def main():
    async with environment() as container, backend_http(container):
        result = await exercise(container)
    print(json.dumps({**result, "fixture_data_removed": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as error:
        print(
            json.dumps(
                {
                    "stage": STAGE,
                    "error": type(error).__name__,
                    "frames": [
                        {"function": frame.name, "line": frame.lineno}
                        for frame in traceback.extract_tb(error.__traceback__)[-4:]
                    ],
                }
            )
        )
        sys.exit(1)
