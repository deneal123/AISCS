"""Реальная правка UI между read receipt и final: устаревший read не завершает задачу."""

import asyncio
import hashlib
import json
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.environment import backend_http, environment
from scripts.harness.live.worker_assertions import read_balance
from scripts.harness.live.worker_process import deliver, prefork_worker
from scripts.harness.live.worker_setup import funded_job
from service.shared.task_contract import CompletionVerifier, TaskState

QUESTION = "Прочитай hello_world.py и объясни его содержимое. Ничего не меняй и не запускай."
CONTENT = "print('user edit preserved')\n"
MODELS = {
    "gigachat": "GigaChat-3-Lightning",
    "routerai": "openai/gpt-4o-mini",
    "openai": "gpt-4o-mini",
}
STAGE = "environment"


async def facts(container, scope, job):
    async with container.infra.pg_connector.get_session_context() as db:
        row = (
            (
                await db.execute(
                    text(
                        "SELECT j.status,j.payload,t.checkpoint,t.admission,t.settled_credits "
                        "FROM profile.user_launch j JOIN profile.harness_task t ON t.task_id=j.id "
                        "WHERE j.id=:job"
                    ),
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
                        "SELECT operation_id,intent,status,receipt FROM profile.harness_operation "
                        "WHERE task_id=:job "
                        "ORDER BY created_at,operation_id"
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
                        "SELECT operation_id,state,receipt FROM profile.harness_grant "
                        "WHERE task_id=:job "
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
    state = TaskState.model_validate(row["checkpoint"]["state"])
    assert len(operations) == 1 and operations[0]["intent"]["name"] == "ide_read_file"
    assert operations[0]["status"] == "succeeded" and len(state.evidence) == 1
    assert row["admission"].get("workspace_id")
    return {
        "task": dict(row),
        "operations": [dict(op) for op in operations],
        "grants": [dict(grant) for grant in grants],
        "charges": charges,
    }, state


async def write_as_user(scope, generation):
    from service.models.key_value import UserTypes
    from service.services.profile.application.auth_service import AuthService
    from service.settings import config

    token = AuthService._create_jwt(
        SimpleNamespace(config=config.auth), scope.user_id, None, UserTypes.REGISTERED
    )
    base = f"http://127.0.0.1:8002/api/chats/{scope.thread_id}/ide/repositories/{scope.repository_id}/files"
    async with httpx.AsyncClient(
        timeout=30, cookies={"auth_token": token}, headers={"X-Workspace-Session": uuid4().hex}
    ) as client:
        lease = await client.post(
            base + "/lease",
            json={
                "path": "hello_world.py",
                "generation": generation,
                "action": "acquire",
            },
        )
        assert lease.status_code == 200, "acceptance_ui_lease_failed"
        response = await client.post(
            base + "/write",
            json={
                "path": "hello_world.py",
                "generation": generation,
                "operation": "file",
                "content": CONTENT,
                "expected_digest": hashlib.sha256(b"print('hello world')\n").hexdigest(),
                "fence": lease.json()["fence"],
            },
        )
        assert response.status_code == 200, "acceptance_ui_write_failed"


async def exercise(container):
    global STAGE
    from service.composition.ide import build_ide_runtime
    from service.settings import config

    provider = os.environ["HARNESS_ACCEPTANCE_PROVIDER"]
    scope, job, before, kwargs = await funded_job(
        container,
        question=QUESTION,
        create_file=True,
        selected_model=MODELS[provider],
    )
    queue = "harness-" + uuid4().hex
    headers = {"Authorization": "Bearer " + config.agents.llm_gateway_api_key}
    async with httpx.AsyncClient(timeout=5, headers=headers) as agent:
        async with prefork_worker(config.pg.db, queue) as (app, first_pid):
            STAGE = "wait_read_barrier"
            delivery = asyncio.create_task(deliver(app, queue, kwargs))
            async with asyncio.timeout(100):
                while True:
                    assert not delivery.done(), "acceptance_worker_finished_before_read_barrier"
                    view = (
                        await agent.get("http://agents:8091/__harness_acceptance__/transport")
                    ).json()
                    if view.get("read_barrier_waiting"):
                        break
                    await asyncio.sleep(0.2)
            initial, current = await facts(container, scope, job)
            assert CompletionVerifier.evaluate(current)["confirmed"] == ["source"]
            STAGE = "concurrent_ui_write"
            await write_as_user(scope, kwargs["session_data"]["_ide_context"]["generation"])
            changed, stale = await facts(container, scope, job)
            assert stale.source_revision != current.source_revision
            assert CompletionVerifier.evaluate(stale)["unchecked"] == ["source"]
            assert changed["operations"] == initial["operations"]
            await agent.post("http://agents:8091/__harness_acceptance__/release-read")
            STAGE = "stale_terminal"
            await delivery
            terminal, final = await facts(container, scope, job)
            result = terminal["task"]["payload"]["metadata"]["task_result"]
            assert result["status"] in {"partial", "blocked"} and not result["verified"]
            assert result["unchecked"] == ["source"]
            assert final.evidence == current.evidence and terminal["charges"] == 1
            assert all(grant["state"] in {"succeeded", "waived"} for grant in terminal["grants"])
            spent = terminal["task"]["settled_credits"]
            assert spent > 0 and before - await read_balance(container, scope) == spent
            observed = (
                await agent.get("http://agents:8091/__harness_acceptance__/transport")
            ).json()
            STAGE = "duplicate_delivery"
            await deliver(app, queue, kwargs)
            assert await facts(container, scope, job) == (terminal, final)
            assert (
                await agent.get("http://agents:8091/__harness_acceptance__/transport")
            ).json() == observed
        STAGE = "restart_delivery"
        async with prefork_worker(config.pg.db, queue) as (app, second_pid):
            assert second_pid != first_pid
            await deliver(app, queue, kwargs)
            assert await facts(container, scope, job) == (terminal, final)
            assert (
                await agent.get("http://agents:8091/__harness_acceptance__/transport")
            ).json() == observed
    runtime = build_ide_runtime(container.infra.pg_connector)
    resolved = await runtime.resolve(scope)
    actual = await runtime.client.read(
        scope.user_id, resolved.binding, operation="file", path="hello_world.py"
    )
    assert actual["content"] == CONTENT
    assert before - await read_balance(container, scope) == spent
    return {
        "stale_read_blocked": True,
        "user_edit_preserved": True,
        "agent_mutations": 0,
        "commands": 0,
        "charges": 1,
        "replay_unchanged": True,
        "restart_replay_unchanged": True,
    }


async def main():
    from scripts.harness.live.provider_profile import isolate_read_change

    isolate_read_change()
    async with environment() as container, backend_http(container):
        outcome = await exercise(container)
    print(json.dumps({**outcome, "fixture_data_removed": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as error:
        print(json.dumps({"stage": STAGE, "error": type(error).__name__}))
        sys.exit(1)
