"""Stop после committed grant, но до первого платного dispatch: настоящий worker и БД."""

import asyncio
import json
import logging
import sys
import traceback
from uuid import uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.crash_boundary import CrashAfterWrite
from scripts.harness.live.environment import backend_http, environment
from scripts.harness.live.retry_barrier import operation_ids
from scripts.harness.live.worker_assertions import read_balance
from scripts.harness.live.worker_process import deliver, prefork_worker
from scripts.harness.live.worker_setup import funded_job

logging.disable(logging.CRITICAL)


class StopAfterGrant(CrashAfterWrite):
    def matches(self, payload):
        return not self.count and self.callback is not None and payload.get("opcode") == "grant"


async def exercise(container, fault):
    from service.models.key_value import UserTypes
    from service.settings import config

    task_id = str(uuid4())
    scope, job, balance, kwargs = await funded_job(container, task_id=task_id)
    token = container.services.auth_service._create_jwt(scope.user_id, None, UserTypes.REGISTERED)

    async def stop():
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8002", cookies={"auth_token": token}, timeout=5
        ) as client:
            response = await client.post("/api/jobs/v1/task/" + task_id + "/cancel")
            assert response.status_code == 200 and response.json()["cancelled"] is True

    fault.callback = stop
    queue = "harness-" + uuid4().hex
    async with prefork_worker(config.pg.db, queue) as (app, _pid):
        result = await deliver(app, queue, kwargs, task_id=task_id)
        if fault.task is not None:
            await fault.task
        assert fault.count == 1
        assert result["status"] == "success", "stop_before_dispatch_not_settled"
        task = result["metadata"]["task_result"]
        assert task["status"] == "cancelled" and task["verified"] is False
        assert task["confirmed"] == [] and task["unchecked"] == ["contract"]
        assert await read_balance(container, scope) == balance
        async with container.infra.pg_connector.get_session_context() as db:
            assert await db.scalar(text("SELECT count(*) FROM profile.harness_operation")) == 0
            assert (
                await db.scalar(
                    text("SELECT count(*) FROM profile.harness_grant WHERE state!='waived'")
                )
                == 0
            )
            assert await db.scalar(text("SELECT settled_credits FROM profile.harness_task")) == 0
            assert (
                await db.scalar(text("SELECT status FROM profile.token_reservations"))
                == "committed"
            )
            events = await db.scalar(text("SELECT count(*) FROM profile.billing_events"))
        async with httpx.AsyncClient(
            base_url="http://agents:8091",
            timeout=5,
            headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key},
        ) as client:
            before = (await client.get("/__harness_acceptance__/transport")).json()
            assert before["completions"] == before["blocked_requests"] == 0
            operations = await operation_ids(container, job)
            replay = await deliver(app, queue, kwargs)
            assert replay["metadata"]["task_result"] == task
            assert (await client.get("/__harness_acceptance__/transport")).json() == before
            assert await operation_ids(container, job) == operations
        assert await read_balance(container, scope) == balance
        async with container.infra.pg_connector.get_session_context() as db:
            assert await db.scalar(text("SELECT count(*) FROM profile.billing_events")) == events
    return {
        "stop_before_dispatch_verified": True,
        "model_calls": 0,
        "project_effects": 0,
        "spent_credits": 0,
    }


async def main():
    fault = StopAfterGrant()
    async with environment() as container, backend_http(container, crash=fault):
        outcome = await exercise(container, fault)
    print(json.dumps({**outcome, "fixture_data_removed": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as error:
        print(
            json.dumps(
                {
                    "stage": "stop_before_dispatch",
                    "error": type(error).__name__,
                    "frames": [
                        {"function": frame.name, "line": frame.lineno}
                        for frame in traceback.extract_tb(error.__traceback__)[-4:]
                    ],
                }
            )
        )
        sys.exit(1)
