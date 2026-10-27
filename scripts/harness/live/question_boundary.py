"""Отказные HTTP-границы вопроса и подтверждения цены через настоящий worker."""

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
from scripts.harness.live.question import transport_status
from scripts.harness.live.question_assertions import final_evidence, job_row, pause_evidence
from scripts.harness.live.worker_assertions import read_balance
from scripts.harness.live.worker_process import deliver, prefork_worker
from scripts.harness.live.worker_setup import funded_job

STAGE = "environment"


async def expire_question(container, question):
    async with container.infra.pg_connector.get_session_context() as db:
        await db.execute(
            text(
                "UPDATE profile.human_question SET expires_at=created_at "
                "WHERE question_id=:question"
            ),
            {"question": UUID(question["question_id"])},
        )
        await db.commit()


async def expire_cost(container, child):
    async with container.infra.pg_connector.get_session_context() as db:
        await db.execute(
            text(
                "UPDATE profile.user_launch SET payload=jsonb_set(payload::jsonb,"
                "'{_human_question_cost_v1,expires_at}',to_jsonb(extract(epoch FROM "
                "clock_timestamp()-interval '1 second'))) WHERE id=:child"
            ),
            {"child": child},
        )
        await db.commit()


async def stop_child(client, child):
    response = await client.post(f"/api/jobs/v1/task/{child}/cancel")
    assert response.status_code == 200 and response.json()["cancelled"] is True


async def pending_boundary(container, client, url, question, payload, mode):
    if mode == "expiry":
        # Сдвигается только срок этой синтетической записи, не системные часы.
        await expire_question(container, question)
        expected = "expired"
    else:
        response = await client.post(url + "/cancel", json={})
        assert response.status_code == 200
        expected = "cancelled"
    for _ in range(2):
        observed = await client.get(url)
        assert observed.status_code == 200 and observed.json()["state"] == expected
        late = await client.post(url + "/answer", json=payload)
        assert late.status_code == 200 and late.json()["state"] == expected
        assert late.json()["resume_job_id"] is None
    return None


async def cost_boundary(container, client, url, payload, mode):
    response = await client.post(url + "/answer", json=payload)
    assert response.status_code == 200 and response.json()["state"] == "accepted"
    child = UUID(response.json()["resume_job_id"])
    offer = (await client.get(url + "/cost")).json()
    assert offer["state"] == "pending"
    if mode == "stop_child":
        await stop_child(client, child)
        view = (await client.get(url + "/cost")).json()
        assert view["state"] == "cancelled"
        refused = await client.post(
            url + "/cost", json={"offer_id": offer["offer_id"], "decision": "accept"}
        )
        assert refused.status_code == 409
    elif mode == "cost_expiry":
        await expire_cost(container, child)
        for _ in range(2):
            late = await client.post(
                url + "/cost", json={"offer_id": offer["offer_id"], "decision": "accept"}
            )
            assert late.status_code == 200 and late.json()["state"] == "expired"
            assert (await job_row(container, child))["status"] == "NEW"
        await stop_child(client, child)
    elif mode == "cost_decline":
        for _ in range(2):
            refused = await client.post(
                url + "/cost", json={"offer_id": offer["offer_id"], "decision": "decline"}
            )
            assert refused.status_code == 200 and refused.json()["state"] == "declined"
    else:
        accepted = await client.post(
            url + "/cost", json={"offer_id": offer["offer_id"], "decision": "accept"}
        )
        assert accepted.status_code == 503
        assert accepted.json()["detail"]["code"] == "human_question_status_unknown"
        # После неизвестного ACK сначала чтение того же решения, не новый offer.
        known = await client.get(url + "/cost")
        assert known.status_code == 200 and known.json()["state"] == "accepted"
        assert known.json()["offer_id"] == offer["offer_id"]
        replay = await client.post(
            url + "/cost", json={"offer_id": offer["offer_id"], "decision": "accept"}
        )
        assert replay.status_code == 200 and replay.json() == known.json()
    return child


async def assert_no_effects(container, scope, root, child, initial, spent):
    async with container.infra.pg_connector.get_session_context() as db:
        assert await db.scalar(text("SELECT count(*) FROM profile.harness_operation")) == 0
        assert await db.scalar(text("SELECT count(*) FROM profile.harness_grant")) == 1
        assert await db.scalar(text("SELECT count(*) FROM profile.billing_events")) == 1
        assert await db.scalar(text("SELECT count(*) FROM profile.user_launch")) == 1 + int(
            child is not None
        )
        assert await db.scalar(text("SELECT active_job_id FROM profile.harness_task")) == root
    if child is not None:
        row = await job_row(container, child)
        assert row["status"] == "FAILURE" and not row["payload"].get("_execution_attempt_v1")
    assert initial - await read_balance(container, scope) == spent
    observed = await transport_status()
    assert observed["completions"] == 1 and observed["blocked_requests"] == 0


async def idle_outbox(app, queue):
    handle = app.send_task(
        "service.infrastructure.messaging.tasks.dispatch_human_question_children", queue=queue
    )
    async with asyncio.timeout(30):
        while not await asyncio.to_thread(handle.ready):
            await asyncio.sleep(0.1)
    result = await asyncio.to_thread(handle.get, timeout=5, propagate=False)
    await asyncio.to_thread(handle.forget)
    assert result == {"status": "success", "claimed": 0, "acknowledged": 0, "deferred": 0}


async def exercise(container, mode):
    global STAGE
    from service.models.key_value import UserTypes
    from service.settings import config

    scope, root, initial, kwargs = await funded_job(
        container,
        question=("Создай простой Python-скрипт, который печатает hello world, и проверь запуск."),
    )
    queue = "harness-" + uuid4().hex
    STAGE = "root_question"
    async with prefork_worker(config.pg.db, queue) as (app, _pid):
        await deliver(app, queue, kwargs)
        question, spent = await pause_evidence(container, scope, root)
    token = container.services.auth_service._create_jwt(scope.user_id, None, UserTypes.REGISTERED)
    url = f"/api/chats/{scope.thread_id}/runs/{root}/questions/{question['question_id']}"
    payload = {
        "intent_id": str(uuid4()),
        "answer": {"choice_id": None, "text": "hello_world.py"},
        "surface": "ide",
        "ide_context": kwargs["session_data"]["_ide_context"],
    }
    STAGE = "http_" + mode
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8002", timeout=15, cookies={"auth_token": token}
    ) as client:
        child = await (
            pending_boundary(container, client, url, question, payload, mode)
            if mode in {"cancel", "expiry"}
            else cost_boundary(container, client, url, payload, mode)
        )
    child_kwargs = {
        "job_id": str(child),
        "thread_id": str(scope.thread_id),
        "user_id": str(scope.user_id),
        "text": "",
        "session_data": {"_human_question_resume_job_v1": str(child)},
    }
    STAGE = "worker_after_" + mode
    async with prefork_worker(config.pg.db, queue, additional_queues=("agents", "maintenance")) as (
        app,
        _pid,
    ):
        if mode == "cost_ack":
            await wait_terminal(container, child)
            first = await final_evidence(container, scope, root, child, kwargs["text"])
            assert initial - first["balance"] == first["spent"]
            observed = await transport_status()
            assert observed["completions"] == 7 and observed["blocked_requests"] == 0
            await deliver(app, queue, child_kwargs)
            assert await final_evidence(container, scope, root, child, kwargs["text"]) == first
            assert await transport_status() == observed
        else:
            await idle_outbox(app, queue)
            if child is not None:
                await deliver(app, queue, child_kwargs)
            await assert_no_effects(container, scope, root, child, initial, spent)
    return {
        "question_boundary_verified": mode,
        "replay_unchanged": True,
        "commands": int(mode == "cost_ack"),
    }


async def main():
    logging.disable(logging.CRITICAL)
    from service.settings import config

    # Только этот процесс/его worker; источник решения о дорогом запуске остаётся штатным.
    config.billing.expensive_run_confirmation_credits = 1
    os.environ["BILLING__EXPENSIVE_RUN_CONFIRMATION_CREDITS"] = "1"
    mode = os.environ["HARNESS_ACCEPTANCE_QUESTION_BOUNDARY"]
    assert mode in {"cancel", "expiry", "stop_child", "cost_decline", "cost_expiry", "cost_ack"}
    async with environment() as container, backend_http(container) as fault:
        result = await exercise(container, mode)
        assert fault.count == int(mode == "cost_ack")
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
