"""Worker → вопрос → HTTP-ответ → настоящий outbox → worker → исполнение и settlement."""

import asyncio
import json
import logging
import os
import sys
import traceback
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.crash import wait_terminal
from scripts.harness.live.environment import backend_http, environment
from scripts.harness.live.question_assertions import final_evidence, job_row, pause_evidence
from scripts.harness.live.worker_process import deliver, prefork_worker
from scripts.harness.live.worker_setup import funded_job

STAGE = "environment"


async def transport_status():
    from service.settings import config

    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(
            "http://agents:8091/__harness_acceptance__/transport",
            headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key},
        )
        assert response.status_code == 200
        return response.json()


async def answer(container, scope, root, question, kwargs):
    from service.models.key_value import UserTypes

    token = container.services.auth_service._create_jwt(scope.user_id, None, UserTypes.REGISTERED)
    url = f"/api/chats/{scope.thread_id}/runs/{root}/questions/{question['question_id']}"
    payload = {
        "intent_id": str(uuid4()),
        "answer": {"choice_id": None, "text": "hello_world.py"},
        "surface": "ide",
        "ide_context": kwargs["session_data"]["_ide_context"],
    }
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8002", timeout=15, cookies={"auth_token": token}
    ) as client:
        for _ in range(2):
            response = await client.get(url)
            assert response.status_code == 200 and response.json() == question
        before = await transport_status()
        from scripts.harness.live.question_assertions import model_call_count

        assert before["completions"] == await model_call_count(container, root)
        assert before["blocked_requests"] == 0
        response = await client.post(url + "/answer", json=payload)
        if response.status_code != 200:
            detail = response.json().get("detail") or {}
            print(
                json.dumps(
                    {
                        "stage": "question_answer_http",
                        "status": response.status_code,
                        "code": detail.get("code") if isinstance(detail, dict) else None,
                    }
                ),
                flush=True,
            )
        assert response.status_code == 200, "acceptance_question_answer_rejected"
        accepted = response.json()
        assert accepted["state"] == "accepted" and accepted["resume_job_id"]
        # Повтор доставляет прежний intent; новый child вручную не создаётся и не запускается.
        replay = await client.post(url + "/answer", json=payload)
        assert replay.status_code == 200 and replay.json() == accepted
        cost = await client.get(url + "/cost")
        assert cost.status_code == 200
        decision = cost.json()
        if decision["state"] == "pending":
            decision_response = await client.post(
                url + "/cost",
                json={
                    "offer_id": decision["offer_id"],
                    "decision": "accept",
                },
            )
            assert decision_response.status_code == 200
            assert decision_response.json()["state"] == "accepted"
        else:
            assert decision["state"] == "not_required"
    return UUID(accepted["resume_job_id"])


async def exercise(container):
    global STAGE
    from service.settings import config

    assert os.environ["CELERY__BROKER_URL"].startswith("redis://gpthub-harness-broker-")
    assert config.human_questions.enabled is True
    scope, root, initial, kwargs = await funded_job(
        container,
        question=(
            "Создай простой Python-скрипт, который печатает hello world, и проверь его запуск."
        ),
    )
    reviewed = os.environ.get("HARNESS_ACCEPTANCE_REVIEW_QUESTIONS") == "true"
    queue = "harness-" + uuid4().hex
    STAGE = "worker_question"
    async with prefork_worker(config.pg.db, queue, additional_queues=("agents", "maintenance")) as (
        app,
        pid,
    ):
        result = await deliver(app, queue, kwargs)
        task = (result.get("metadata") or {}).get("task_result") or {}
        if task.get("status") != "waiting_user":
            print(
                json.dumps(
                    {
                        "stage": STAGE,
                        "task_status": task.get("status"),
                        "blocker": task.get("blocker"),
                    }
                ),
                flush=True,
            )
        question, spent = await pause_evidence(container, scope, root)
        assert spent > 0
        if reviewed:
            async with container.infra.pg_connector.get_session_context() as db:
                assert (
                    await db.scalar(
                        text(
                            "SELECT count(*) FROM profile.harness_grant WHERE task_id=:task "
                            "AND request->>'_admission_job_v1'=:root"
                        ),
                        {"task": root, "root": str(root)},
                    )
                    == 2
                )
        before = await transport_status()
        await deliver(app, queue, kwargs)
        assert await transport_status() == before
    STAGE = "authenticated_answer_without_worker"
    child = await answer(container, scope, root, question, kwargs)
    pending = await job_row(container, child)
    assert pending["status"] == "NEW" and not pending["payload"].get("_execution_attempt_v1")
    assert await transport_status() == before
    STAGE = "restart_for_outbox_child"
    async with prefork_worker(config.pg.db, queue, additional_queues=("agents", "maintenance")) as (
        app,
        child_pid,
    ):
        assert child_pid != pid
        STAGE = "outbox_worker_completion"
        await wait_terminal(container, child)
        first = await final_evidence(container, scope, root, child, kwargs["text"])
        assert initial - first["balance"] == first["spent"]
        observed = await transport_status()
        assert observed["completions"] == first["model_calls"] and observed["blocked_requests"] == 0
        child_kwargs = {
            "job_id": str(child),
            "thread_id": str(scope.thread_id),
            "user_id": str(scope.user_id),
            "text": "",
            "session_data": {"_human_question_resume_job_v1": str(child)},
        }
        STAGE = "child_redelivery"
        await deliver(app, queue, child_kwargs)
        assert await final_evidence(container, scope, root, child, kwargs["text"]) == first
        assert await transport_status() == observed
    STAGE = "worker_restart_redelivery"
    async with prefork_worker(config.pg.db, queue) as (app, restarted_pid):
        assert child_pid != restarted_pid
        await deliver(app, queue, child_kwargs)
        assert await final_evidence(container, scope, root, child, kwargs["text"]) == first
        assert await transport_status() == observed
    return {
        "question_harness_verified": True,
        "outbox_worker_resumed": True,
        "replay_and_restart_unchanged": True,
        "command_effects": 1,
        "usage_charges": 2,
        **({"reviewed_question_resume_verified": True} if reviewed else {}),
    }


async def main():
    logging.disable(logging.CRITICAL)
    async with environment() as container, backend_http(container) as fault:
        result = await exercise(container)
        assert fault.count == int(bool(os.environ.get("HARNESS_ACCEPTANCE_LOST_ACK")))
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
