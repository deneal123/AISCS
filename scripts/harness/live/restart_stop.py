"""Stop между committed retry intent и автоматической доставкой того же задания."""

import asyncio
import json
from uuid import uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.crash import task_row
from scripts.harness.live.retry_barrier import consumer, operation_ids, stop_pending
from scripts.harness.live.worker_assertions import read_balance
from scripts.harness.live.worker_process import deliver, prefork_worker
from scripts.harness.live.worker_setup import funded_job


async def facts(container, job):
    async with container.infra.pg_connector.get_session_context() as db:
        result = await db.scalar(
            text(
                "SELECT payload->'metadata'->'task_result' FROM profile.user_launch WHERE id=:job"
            ),
            {"job": job},
        )
        assert result["status"] == "cancelled" and result["verified"] is False
        assert "script" in result["confirmed"] and "verify_project" in result["unchecked"]
        assert await db.scalar(text("SELECT count(*) FROM profile.billing_events")) == 1
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM profile.harness_operation "
                    "WHERE intent->>'name'='ide_write_file'"
                )
            )
            == 1
        )
        assert (
            await db.scalar(
                text("SELECT count(*) FROM profile.harness_operation WHERE command IS NOT NULL")
            )
            == 0
        )
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM profile.harness_grant "
                    "WHERE state NOT IN ('succeeded','waived')"
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                text("SELECT COALESCE(sum(command_pins),0) FROM profile.ide_checkpoint_intent")
            )
            == 0
        )
        assert await db.scalar(text("SELECT status FROM profile.token_reservations")) == "committed"
    return result


async def exercise(container, fault, restart_agents):
    from service.models.key_value import UserTypes
    from service.services.chat.application.harness_capability import HarnessOwner, issue
    from service.settings import config

    task_id = str(uuid4())
    scope, job, balance, kwargs = await funded_job(container, task_id=task_id)
    fault.job_id = str(job)
    token = container.services.auth_service._create_jwt(scope.user_id, None, UserTypes.REGISTERED)
    queue = "harness-" + uuid4().hex
    observer = None
    async with httpx.AsyncClient(
        base_url="http://agents:8091",
        timeout=5,
        headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key},
    ) as client:

        async def interrupt():
            nonlocal observer
            await consumer(app, queue, enabled=False)
            # Очередь уже закрыта: дождёмся готовности нового agents прежде,
            # чем читать его счётчики. Оборванный HTTP не должен сорвать сам Stop.
            await restart_agents(client)
            observer = asyncio.create_task(
                stop_pending(container, job, task_id, token, app, queue, client)
            )

        fault.callback = interrupt
        try:
            async with prefork_worker(config.pg.db, queue) as (app, _pid):
                try:
                    result = await deliver(app, queue, kwargs, task_id=task_id)
                except BaseException:
                    if fault.task is not None and fault.task.done():
                        await fault.task
                    if observer is not None and observer.done():
                        await observer
                    raise
                if fault.count != 1 or observer is None:
                    print(
                        json.dumps(
                            {
                                "stage": "retry_stop_boundary",
                                "harness_exchanges": fault.responses[-16:],
                            }
                        ),
                        flush=True,
                    )
                assert fault.count == 1 and observer is not None
                before = await observer
                assert (
                    result["status"] == "success"
                    and result["metadata"]["task_result"]["status"] == "cancelled"
                )
                saved = await facts(container, job)
                current = await task_row(container, job)
                assert (
                    balance - await read_balance(container, scope) == current["settled_credits"] > 0
                )
                transport = (await client.get("/__harness_acceptance__/transport")).json()
                assert transport == before["transport"]
                assert await operation_ids(container, job) == before["operations"]
                assert before["retry"]["count"] == 1
                owner = HarnessOwner(
                    task_id=str(job),
                    job_id=str(job),
                    user_id=str(scope.user_id),
                    thread_id=str(scope.thread_id),
                    attempt_id=str(current["execution_attempt_id"]),
                    epoch=current["fencing_epoch"],
                    project_id=str(scope.repository_id),
                    generation=current["admission"]["generation"],
                )
                async with httpx.AsyncClient(timeout=5) as backend:
                    denied = await backend.post(
                        "http://127.0.0.1:8002/internal/harness/v1/exchange",
                        headers={"Authorization": "Bearer " + issue(owner)},
                        json={
                            "opcode": "grant",
                            "call": {
                                "operation_id": str(uuid4()),
                                "provider": "gigachat",
                                "model": "GigaChat-3-Lightning",
                                "prompt": 1,
                                "completion": 1,
                                "request_digest": "0" * 64,
                            },
                        },
                    )
                assert denied.status_code == 409 and denied.json()["detail"]["code"] == "cancelled"
                assert (await deliver(app, queue, kwargs))["status"] == "success"
                assert await facts(container, job) == saved
                assert (await client.get("/__harness_acceptance__/transport")).json() == transport
        finally:
            if observer is not None and not observer.done():
                observer.cancel()
                await asyncio.gather(observer, return_exceptions=True)
    return {"agents_restart_stopped": True, "write_effects": 1, "command_effects": 0, "charges": 1}
