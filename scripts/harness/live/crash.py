"""Actual prefork SIGKILL and broker redelivery after a committed file checkpoint."""

import asyncio
import json
import logging
import os
import sys
import traceback
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.crash_boundary import CrashAfterWrite, kill_owned_child
from scripts.harness.live.environment import backend_http, environment
from scripts.harness.live.worker_assertions import evidence
from scripts.harness.live.worker_process import prefork_worker
from scripts.harness.live.worker_setup import funded_job

logging.disable(logging.CRITICAL)
STAGE = "environment"


async def task_row(container, job):
    async with container.infra.pg_connector.get_session_context() as db:
        return (
            (
                await db.execute(
                    text("SELECT * FROM profile.harness_task WHERE task_id=:job"), {"job": job}
                )
            )
            .mappings()
            .one()
        )


async def wait_terminal(container, job):
    async with asyncio.timeout(160):
        while True:
            async with container.infra.pg_connector.get_session_context() as db:
                row = (
                    (
                        await db.execute(
                            text("SELECT status,payload FROM profile.user_launch WHERE id=:job"),
                            {"job": job},
                        )
                    )
                    .mappings()
                    .one()
                )
            if row["status"] in {"SUCCESS", "FAILURE"}:
                return row
            await asyncio.sleep(0.1)


async def exercise(container, fault):
    global STAGE
    from service.services.chat.application.harness_capability import HarnessOwner, issue
    from service.settings import config
    from service.shared.task_contract import TaskState

    STAGE = "prepare_crash_job"
    scope, job, balance, kwargs = await funded_job(container)
    fault.job_id = str(job)
    queue = "harness-" + uuid4().hex
    killed = {}
    resume_tuning = os.environ.get("HARNESS_ACCEPTANCE_RESUME_TUNING") == "true"
    async with prefork_worker(config.pg.db, queue) as (app, parent_pid):

        async def kill_at_boundary():
            old = await task_row(container, job)
            if fault.mode == "provider_receipt":
                async with container.infra.pg_connector.get_session_context() as db:
                    stored = await db.scalar(
                        text(
                            "SELECT receipt FROM profile.harness_grant "
                            "WHERE task_id=:job AND operation_id=:operation"
                        ),
                        {"job": job, "operation": UUID(fault.boundary["receipt"]["operation_id"])},
                    )
                    assert stored["provider_state"] == fault.boundary["receipt"]["provider_state"]
                if resume_tuning:
                    from scripts.harness.live.replay import change_resume_tuning

                    await change_resume_tuning(
                        container, job, fault.boundary["receipt"]["operation_id"]
                    )
            inspector = app.control.inspect(destination=[queue + "@acceptance"], timeout=2)
            stats = await asyncio.to_thread(inspector.stats)
            children = stats[queue + "@acceptance"]["pool"]["processes"]
            assert len(children) == 1
            await asyncio.to_thread(kill_owned_child, children[0], parent_pid, config.pg.db)
            killed.update(pid=children[0], owner=dict(old))
            async with asyncio.timeout(30):
                while (await task_row(container, job))["fencing_epoch"] <= old["fencing_epoch"]:
                    await asyncio.sleep(0.1)

        fault.callback = kill_at_boundary
        STAGE = "prefork_sigkill_and_redelivery"
        handle = app.send_task(
            "service.services.chat.infrastructure.chat_worker_tasks.process_agent_message",
            queue=queue,
            kwargs=kwargs,
        )
        terminal = await wait_terminal(container, job)
        if fault.task:
            await fault.task
        task_result = terminal["payload"].get("metadata", {}).get("task_result") or {}
        if task_result.get("status") != "completed":
            print(
                json.dumps(
                    {
                        "stage": STAGE,
                        "task_status": task_result.get("status"),
                        "blocker": task_result.get("blocker"),
                        "job_status": terminal["status"],
                    }
                ),
                flush=True,
            )
        STAGE = "verify_crash_recovery"
        assert fault.count == 1 and killed
        facts = await evidence(container, scope, job)
        assert balance - facts["balance"] == facts["spent"]
        latest = await task_row(container, job)
        old = killed["owner"]
        assert latest["execution_attempt_id"] != old["execution_attempt_id"]
        assert latest["fencing_epoch"] > old["fencing_epoch"]
        assert latest["admission"] == old["admission"]
        # Wire excludes None; compare canonical typed contracts, not JSON omission.
        saved = TaskState.model_validate(old["checkpoint"]["state"]).model_dump(mode="json")
        state = latest["checkpoint"]["state"]
        expected_rounds = 3 if fault.mode == "provider_receipt" else 2
        assert saved["rounds"] == expected_rounds and state["rounds"] == 5
        assert state["contract"] == saved["contract"]
        assert state["repairs"] == saved["repairs"] == 0
        assert state["budget"]["active_ms"] >= saved["budget"]["active_ms"]
        for key in ("provider", "model"):
            assert latest["continuation"]["provider"][key] == old["continuation"]["provider"][key]
        if fault.mode == "provider_receipt":
            assert (
                fault.boundary["receipt"]["provider_state"]["state_id"]
                != (old["continuation"]["provider"]["state_id"])
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
        old_owner = HarnessOwner(
            task_id=str(job),
            job_id=str(job),
            thread_id=str(scope.thread_id),
            user_id=str(scope.user_id),
            attempt_id=str(old["execution_attempt_id"]),
            epoch=old["fencing_epoch"],
            project_id=old["admission"]["project_id"],
            generation=old["admission"]["generation"],
        )
        async with httpx.AsyncClient(timeout=5) as client:
            denied = await client.post(
                "http://127.0.0.1:8002/internal/harness/v1/exchange",
                json={"opcode": "state"},
                headers={"Authorization": "Bearer " + issue(old_owner)},
            )
            assert denied.status_code in {403, 409}
            assert denied.json()["detail"]["code"] == "harness_fenced"
            observed = (
                await client.get(
                    "http://agents:8091/__harness_acceptance__/transport",
                    headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key},
                )
            ).json()
            assert observed["completions"] == 6 and observed["blocked_requests"] == 0
        if resume_tuning:
            assert len(fault.replayed_grants) == 1
        stats = await asyncio.to_thread(inspector_stats, app, queue)
        assert killed["pid"] not in stats[queue + "@acceptance"]["pool"]["processes"]
        await asyncio.to_thread(handle.forget)
    result = {
        "worker_crash_recovered": True,
        "write_effects": 1,
        "command_effects": 1,
        "charges": 1,
        "old_attempt_fenced": True,
    }
    if resume_tuning:
        result["completed_slot_reused"] = True
    return result


def inspector_stats(app, queue):
    return app.control.inspect(destination=[queue + "@acceptance"], timeout=2).stats()


async def main():
    fault = CrashAfterWrite(os.environ.get("HARNESS_ACCEPTANCE_CRASH_BOUNDARY", "checkpoint"))
    async with environment() as container, backend_http(container, crash=fault):
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
                        {"function": frame.name, "line": frame.lineno}
                        for frame in traceback.extract_tb(error.__traceback__)[-4:]
                    ],
                }
            )
        )
        sys.exit(1)
