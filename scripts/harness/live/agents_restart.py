"""Обрыв настоящего agents-процесса после commit; продолжение того же задания."""

import asyncio
import json
import logging
import os
import sys
import traceback
from uuid import uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.crash import task_row
from scripts.harness.live.crash_boundary import CrashAfterWrite
from scripts.harness.live.environment import backend_http, environment
from scripts.harness.live.worker_assertions import evidence
from scripts.harness.live.worker_process import deliver, prefork_worker
from scripts.harness.live.worker_setup import funded_job

logging.disable(logging.CRITICAL)
STAGE = "environment"


async def restart_agents(client):
    before = (await client.get("/__harness_acceptance__/instance")).json()
    response = await client.post("/__harness_acceptance__/restart")
    assert response.status_code == 200 and response.json() == {"restarting": before["instance"]}
    async with asyncio.timeout(30):
        while True:
            try:
                current = await client.get("/__harness_acceptance__/instance")
                if current.status_code == 200 and current.json() != before:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.1)


async def exercise(container, fault):
    global STAGE
    from service.settings import config

    scope, job, balance, kwargs = await funded_job(container)
    fault.job_id = str(job)
    queue = "harness-" + uuid4().hex
    old_owner = {}
    async with httpx.AsyncClient(
        base_url="http://agents:8091",
        timeout=5,
        headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key},
    ) as client:

        async def interrupt():
            old_owner.update(await task_row(container, job))
            await restart_agents(client)

        fault.callback = interrupt
        async with prefork_worker(config.pg.db, queue) as (app, _pid):
            STAGE = "interrupt_agents_after_checkpoint"
            result = await deliver(app, queue, kwargs)
            if fault.task:
                await fault.task
            async with container.infra.pg_connector.get_session_context() as db:
                status = await db.scalar(
                    text("SELECT status FROM profile.user_launch WHERE id=:job"), {"job": job}
                )
            if status != "SUCCESS" or fault.count != 1:
                runs = (await client.get("/__harness_acceptance__/runs")).json()
                print(
                    json.dumps(
                        {
                            "stage": STAGE,
                            "crash_count": fault.count,
                            "harness_exchanges": fault.responses[-16:],
                            "agent_runs": runs,
                        }
                    ),
                    flush=True,
                )
            assert fault.count == 1, "acceptance_committed_write_boundary_not_reached"
            assert status == "SUCCESS", "acceptance_interrupted_task_not_recovered_automatically"
            STAGE = "verify_automatic_same_task_recovery"
            assert result.get("status") == "success"
            facts = await evidence(container, scope, job)
            assert balance - facts["balance"] == facts["spent"]
            latest = await task_row(container, job)
            assert latest["execution_attempt_id"] != old_owner["execution_attempt_id"]
            assert latest["fencing_epoch"] > old_owner["fencing_epoch"]
            assert latest["admission"] == old_owner["admission"]
            assert latest["checkpoint"]["state"]["rounds"] == 5
            async with container.infra.pg_connector.get_session_context() as db:
                recovery = await db.scalar(
                    text(
                        "SELECT payload->'_harness_transport_retry_v1' "
                        "FROM profile.user_launch WHERE id=:job"
                    ),
                    {"job": job},
                )
            assert 1 <= recovery["count"] <= 3 and recovery["state"] == "pending"
            assert latest["fencing_epoch"] == old_owner["fencing_epoch"] + recovery["count"]
            assert recovery["attempt_id"] != str(latest["execution_attempt_id"])
            if recovery["count"] == 1:
                assert recovery["attempt_id"] == str(old_owner["execution_attempt_id"])
            from service.shared.task_contract import TaskState

            saved = TaskState.model_validate(old_owner["checkpoint"]["state"])
            resumed = TaskState.model_validate(latest["checkpoint"]["state"])
            assert resumed.contract == saved.contract
            assert resumed.repairs == saved.repairs == 0
            assert resumed.budget.active_ms >= saved.budget.active_ms
            for field in ("provider", "model"):
                assert (
                    latest["continuation"]["provider"][field]
                    == old_owner["continuation"]["provider"][field]
                )
            async with container.infra.pg_connector.get_session_context() as db:
                writes = await db.scalar(
                    text(
                        "SELECT count(*) FROM profile.harness_operation WHERE task_id=:job "
                        "AND intent->>'name'='ide_write_file'"
                    ),
                    {"job": job},
                )
                assert writes == 1
            from service.services.chat.application.harness_capability import HarnessOwner, issue

            previous = HarnessOwner(
                task_id=str(job),
                job_id=str(job),
                user_id=str(scope.user_id),
                thread_id=str(scope.thread_id),
                attempt_id=str(old_owner["execution_attempt_id"]),
                epoch=old_owner["fencing_epoch"],
                project_id=str(scope.repository_id),
                generation=old_owner["admission"]["generation"],
            )
            async with httpx.AsyncClient(timeout=5) as backend:
                denied = await backend.post(
                    "http://127.0.0.1:8002/internal/harness/v1/exchange",
                    json={"opcode": "state"},
                    headers={"Authorization": "Bearer " + issue(previous)},
                )
            assert denied.status_code == 409 and denied.json()["detail"]["code"] == "harness_fenced"
            observed = (await client.get("/__harness_acceptance__/transport")).json()
            assert observed["completions"] == 6 and observed["blocked_requests"] == 0
            assert (await deliver(app, queue, kwargs)).get("status") == "success"
            assert await evidence(container, scope, job) == facts
            assert (await client.get("/__harness_acceptance__/transport")).json() == observed
    return {
        "agents_restart_recovered": True,
        "write_effects": 1,
        "command_effects": 1,
        "charges": 1,
        "old_attempt_fenced": True,
    }


async def main():
    fault = CrashAfterWrite()
    async with environment() as container, backend_http(container, crash=fault):
        if os.environ.get("HARNESS_ACCEPTANCE_RESTART_EXHAUSTED") in {
            "after_write",
            "before_dispatch",
        }:
            from scripts.harness.live.restart_exhausted import exercise as exercise_exhausted

            result = await exercise_exhausted(container, fault, restart_agents)
        elif os.environ.get("HARNESS_ACCEPTANCE_RESTART_STOP") == "true":
            from scripts.harness.live.restart_stop import exercise as exercise_stop

            result = await exercise_stop(container, fault, restart_agents)
        else:
            result = await exercise(container, fault)
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
                        {"function": item.name, "line": item.lineno}
                        for item in traceback.extract_tb(error.__traceback__)[-4:]
                    ],
                }
            )
        )
        sys.exit(1)
