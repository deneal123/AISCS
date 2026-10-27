"""Возобновление принятого вопроса в сохранённой fixture, без повторения исходной задачи."""

import asyncio
import json
import logging
import re
import sys
import traceback
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.crash import wait_terminal
from scripts.harness.live.environment import backend_http, environment
from scripts.harness.live.question import transport_status
from scripts.harness.live.question_assertions import final_evidence, job_row
from scripts.harness.live.worker_assertions import read_balance
from scripts.harness.live.worker_process import deliver, prefork_worker

STAGE = "owned_fixture_validation"


async def fixture(container):
    from service.services.chat.domain.ide.runtime import RepositoryScope

    async with container.infra.pg_connector.get_session_context() as db:
        users = (await db.execute(text('SELECT email,password_hash FROM profile."user"'))).all()
        assert len(users) == 1 and users[0].password_hash == "!disabled"
        assert re.fullmatch(r"harness-[a-f0-9-]{36}@example\.test", users[0].email)
        question = (await db.execute(text("SELECT * FROM profile.human_question"))).mappings().one()
        task = (await db.execute(text("SELECT * FROM profile.harness_task"))).mappings().one()
        assert question["state"] == "accepted" and task["checkpoint"] is None
        assert task["active_job_id"] == question["source_job_id"]
        assert task["user_id"] == question["user_id"] and task["thread_id"] == question["thread_id"]
        assert await db.scalar(text("SELECT count(*) FROM profile.harness_operation")) == 0
        states = (await db.execute(text("SELECT state FROM profile.harness_grant"))).scalars().all()
        assert states == ["succeeded"]
    root, child = question["source_job_id"], question["resume_job_id"]
    parent, pending = await job_row(container, root), await job_row(container, child)
    assert parent["status"] == "SUCCESS" and pending["status"] == "NEW"
    assert not pending["payload"].get("_execution_attempt_v1")
    assert pending["payload"]["_human_question_cost_v1"]["state"] in {"not_required", "accepted"}
    assert parent["payload"]["text"] == task["admission"]["goal"]
    scope = RepositoryScope(
        task["thread_id"], task["user_id"], UUID(task["admission"]["project_id"])
    )
    return scope, root, child, question, pending["payload"], task


async def exercise(container):
    global STAGE
    from service.models.key_value import UserTypes
    from service.settings import config

    scope, root, child, question, payload, task = await fixture(container)
    initial = await read_balance(container, scope) + task["settled_credits"]
    queue = "harness-" + uuid4().hex
    token = container.services.auth_service._create_jwt(scope.user_id, None, UserTypes.REGISTERED)
    url = f"/api/chats/{scope.thread_id}/runs/{root}/questions/{question['question_id']}"
    child_kwargs = {
        "job_id": str(child),
        "thread_id": str(scope.thread_id),
        "user_id": str(scope.user_id),
        "text": "",
        "session_data": {"_human_question_resume_job_v1": str(child)},
    }
    async with prefork_worker(config.pg.db, queue, additional_queues=("agents", "maintenance")) as (
        app,
        pid,
    ):
        STAGE = "replayed_answer_outbox"
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8002", timeout=15, cookies={"auth_token": token}
        ) as client:
            response = await client.post(
                url + "/answer",
                json={
                    "intent_id": str(question["answer_intent_id"]),
                    "answer": question["answer"],
                    "surface": "ide",
                    "ide_context": payload["_human_question_context_v1"],
                },
            )
            assert response.status_code == 200 and response.json()["resume_job_id"] == str(child)
        STAGE = "resumed_child_completion"
        terminal = await wait_terminal(container, child)
        summary = (terminal["payload"].get("metadata") or {}).get("task_result") or {}
        if summary.get("status") != "completed":
            print(
                json.dumps(
                    {
                        "stage": STAGE,
                        "task_status": summary.get("status"),
                        "blocker": summary.get("blocker"),
                    }
                ),
                flush=True,
            )
        first = await final_evidence(container, scope, root, child, task["admission"]["goal"])
        assert initial - first["balance"] == first["spent"]
        observed = await transport_status()
        assert observed["completions"] == 6 and observed["blocked_requests"] == 0
        STAGE = "resumed_child_redelivery"
        await deliver(app, queue, child_kwargs)
        assert (
            await final_evidence(container, scope, root, child, task["admission"]["goal"]) == first
        )
        assert await transport_status() == observed
    STAGE = "resumed_worker_restart"
    async with prefork_worker(config.pg.db, queue) as (app, restarted_pid):
        assert restarted_pid != pid
        await deliver(app, queue, child_kwargs)
        assert (
            await final_evidence(container, scope, root, child, task["admission"]["goal"]) == first
        )
        assert await transport_status() == observed
    return {
        "question_harness_verified": True,
        "resumed_existing_question": True,
        "replay_and_restart_unchanged": True,
        "command_effects": 1,
        "usage_charges": 2,
    }


async def main(database):
    logging.disable(logging.CRITICAL)
    async with environment(existing_database=database) as container, backend_http(container):
        result = await exercise(container)
    print(json.dumps({**result, "fixture_data_removed": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[-1]))
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
