"""Authenticated Stop while user code and a detached child run in the real sandbox."""

import asyncio
import json
import logging
import sys
import traceback
from uuid import uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.crash import task_row, wait_terminal
from scripts.harness.live.environment import backend_http, environment
from scripts.harness.live.worker_assertions import read_balance
from scripts.harness.live.worker_process import deliver, prefork_worker
from scripts.harness.live.worker_setup import funded_job

logging.disable(logging.CRITICAL)
STAGE = "environment"


async def command(container, job):
    async with container.infra.pg_connector.get_session_context() as db:
        return await db.scalar(
            text(
                "SELECT command FROM profile.harness_operation WHERE task_id=:job "
                "AND command IS NOT NULL"
            ),
            {"job": job},
        )


async def exercise(container):
    global STAGE
    from service.composition.ide import build_ide_runtime
    from service.models.key_value import UserTypes
    from service.services.chat.application.harness_capability import HarnessOwner, issue
    from service.services.chat.application.ide.edits import IdeEditService
    from service.services.chat.domain.ide.edits import IdeEditError
    from service.settings import config

    STAGE = "prepare_stop_job"
    task_id = str(uuid4())
    scope, job, initial_balance, kwargs = await funded_job(container, task_id=task_id)
    runtime = build_ide_runtime(container.infra.pg_connector)
    binding = (await runtime.resolve(scope)).binding
    queue = "harness-" + uuid4().hex
    async with prefork_worker(config.pg.db, queue) as (app, _pid):
        handle = app.send_task(
            "service.services.chat.infrastructure.chat_worker_tasks.process_agent_message",
            queue=queue,
            task_id=task_id,
            kwargs=kwargs,
        )
        STAGE = "wait_for_running_user_code"
        async with asyncio.timeout(35):
            while True:
                record = await command(container, job)
                if record and record["state"] == "running" and record["dispatch_authorized"]:
                    try:
                        marker = await runtime.client.read(
                            scope.user_id, binding, operation="file", path="started.txt"
                        )
                        if marker.get("content") == "ready":
                            break
                    except Exception:
                        pass
                await asyncio.sleep(0.1)
        assert not record["cleanup_confirmed"]
        STAGE = "mutation_gate_during_command"
        edits = IdeEditService(runtime, container.infra.redis_client)
        generation = kwargs["session_data"]["_ide_context"]["generation"]
        source = await runtime.client.read(
            scope.user_id, binding, operation="file", path="hello_world.py"
        )
        try:
            await edits.write(
                scope,
                path="hello_world.py",
                generation=generation,
                session="harness-user-buffer",
                operation="file",
                content="print('unsaved user buffer')\n",
                expected_digest=source["digest"],
                fence=0,
            )
        except IdeEditError as error:
            assert error.code == "ide_command_busy"
        else:
            raise AssertionError("acceptance_mutation_gate_missing")
        STAGE = "authenticated_stop_request"
        token = container.services.auth_service._create_jwt(
            scope.user_id, None, UserTypes.REGISTERED
        )
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8002", cookies={"auth_token": token}, timeout=10
        ) as client:
            response = await client.post("/api/jobs/v1/task/" + task_id + "/cancel")
            assert response.status_code == 200 and response.json()["cancelled"] is True
        STAGE = "confirm_command_cleanup"
        async with asyncio.timeout(35):
            while True:
                record = await command(container, job)
                if record["cleanup_confirmed"]:
                    break
                await asyncio.sleep(0.1)
        assert record["state"] == "cancelled" and record["stop_reason"] == "cancelled"
        terminal = await wait_terminal(container, job)
        result = terminal["payload"].get("metadata", {}).get("task_result") or {}
        if result.get("status") != "cancelled":
            print(
                json.dumps(
                    {
                        "stage": STAGE,
                        "job_status": terminal["status"],
                        "task_status": result.get("status"),
                        "metadata_keys": list((terminal["payload"].get("metadata") or {}).keys()),
                    }
                ),
                flush=True,
            )
        assert result.get("status") == "cancelled" and result["verified"] is False
        assert "verify_project" in result["unchecked"]
        latest = await task_row(container, job)
        assert latest["settled_credits"] > 0
        remaining = await read_balance(container, scope)
        assert initial_balance - remaining == latest["settled_credits"]
        owner = HarnessOwner(
            task_id=str(job),
            job_id=str(job),
            user_id=str(scope.user_id),
            thread_id=str(scope.thread_id),
            attempt_id=str(latest["execution_attempt_id"]),
            epoch=latest["fencing_epoch"],
            project_id=str(scope.repository_id),
            generation=generation,
        )
        async with httpx.AsyncClient(timeout=5) as client:
            denied = await client.post(
                "http://127.0.0.1:8002/internal/harness/v1/exchange",
                headers={"Authorization": "Bearer " + issue(owner)},
                json={"opcode": "dispatch_effect", "operation_id": str(record["operation_id"])},
            )
            assert denied.status_code == 409 and denied.json()["detail"]["code"] == "cancelled"
            observed = (
                await client.get(
                    "http://agents:8091/__harness_acceptance__/transport",
                    headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key},
                )
            ).json()
            assert observed["completions"] == 5 and observed["blocked_requests"] == 0
            replay = await deliver(app, queue, kwargs)
            assert replay["metadata"]["task_result"] == result
            assert (
                await client.get(
                    "http://agents:8091/__harness_acceptance__/transport",
                    headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key},
                )
            ).json() == observed
        assert await read_balance(container, scope) == remaining
        STAGE = "confirm_gate_released_after_cleanup"
        lease = await edits.lease(
            scope,
            path="hello_world.py",
            generation=generation,
            session="harness-user-buffer",
            action="acquire",
            fence=None,
        )
        await edits.lease(
            scope,
            path="hello_world.py",
            generation=generation,
            session="harness-user-buffer",
            action="release",
            fence=lease["fence"],
        )
        async with container.infra.pg_connector.get_session_context() as db:
            assert (
                await db.scalar(text("SELECT sum(command_pins) FROM profile.ide_checkpoint_intent"))
                == 0
            )
            assert (
                await db.scalar(
                    text("SELECT count(*) FROM profile.harness_operation WHERE command IS NOT NULL")
                )
                == 1
            )
            assert (
                await db.scalar(
                    text("SELECT count(*) FROM profile.billing_events WHERE user_id=:owner"),
                    {"owner": scope.user_id},
                )
                == 1
            )
            assert (
                await db.scalar(
                    text(
                        "SELECT status FROM profile.token_reservations WHERE harness_task_id=:job"
                    ),
                    {"job": job},
                )
                == "committed"
            )
        await asyncio.to_thread(handle.forget)
    return {
        "worker_stop_verified": True,
        "cleanup_confirmed": True,
        "mutation_gate_verified": True,
        "late_dispatch_denied": True,
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
