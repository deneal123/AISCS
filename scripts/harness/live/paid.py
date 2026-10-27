"""One real paid GigaChat harness job; all existing user data is preserved."""

import asyncio
import json
import logging
import sys
import traceback
from uuid import uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.environment import backend_http
from scripts.harness.live.paid_archive import archive_sources
from scripts.harness.live.paid_evidence import evidence
from scripts.harness.live.paid_setup import (
    new_paid_job,
    paid_environment,
    paid_model,
    prepare_paid_project,
)
from scripts.harness.live.worker_process import deliver, prefork_worker

logging.disable(logging.CRITICAL)
STAGE = "paid_environment"


async def metrics():
    from service.settings import config

    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(
            "http://agents:8091/__harness_acceptance__/transport",
            headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key},
        )
        assert response.status_code == 200
        return response.json()


async def retire_test_runtime(container, scope):
    from service.composition.ide import build_ide_runtime
    from service.settings import config

    runtime = build_ide_runtime(container.infra.pg_connector)
    resolved = await runtime.resolve(scope)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(
            "DELETE",
            "http://workspace:8082/workspaces/" + resolved.binding.workspace_id,
            json={"user_id": str(scope.user_id), "token": resolved.binding.token},
            headers={"Authorization": "Bearer " + config.agents.workspace_api_key},
        )
        assert response.status_code == 200 and response.json() == {
            "deleted": resolved.binding.workspace_id
        }
    # Explicit DELETE confirms this disposable runtime is gone. Allocation
    # lookup has no durable tombstone for explicit destruction, so its honest
    # public observation is unknown until TTL expires, not proof of a live process.
    assert (await runtime.status(scope))["workspace"]["state"] in {"unknown", "expired"}


async def exercise(container):
    global STAGE
    from service.settings import config

    async with container.infra.pg_connector.get_session_context() as db:
        old_jobs = set(
            (
                await db.execute(
                    text(
                        "SELECT id FROM profile.user_launch "
                        "WHERE type='CHAT' AND status='PROCESSING'"
                    )
                )
            ).scalars()
        )
    STAGE = "paid_prepare_project"
    scope, generation, before, estimate = await prepare_paid_project(container)
    queue = "harness-paid-" + uuid4().hex
    async with prefork_worker(config.pg.db, queue) as (app, _pid):
        job, task_id, kwargs = await new_paid_job(container, scope, generation)
        print(
            json.dumps(
                {"stage": "paid_job_created", "job_id": str(job), "thread_id": str(scope.thread_id)}
            ),
            flush=True,
        )
        # A single ordinary delivery. Unknown/timeout never submits this job again.
        STAGE = "paid_worker_delivery"
        result = await deliver(app, queue, kwargs, task_id=task_id, timeout=650)
        assert isinstance(result, dict) and result.get("status") == "success", "paid_worker_failed"
        STAGE = "paid_check_independent_receipts"
        first = await evidence(container, scope, job)
        assert before - first["balance"] == first["credits"]
        observed = await metrics()
        assert observed["paid_completions"] > 0 and observed["blocked_mutations"] == 0
        STAGE = "paid_duplicate_delivery"
        replay = await deliver(app, queue, kwargs)
        assert replay.get("status") == "success" and await evidence(container, scope, job) == first
        assert await metrics() == observed
    STAGE = "paid_restarted_worker_redelivery"
    async with prefork_worker(config.pg.db, queue) as (app, _pid):
        replay = await deliver(app, queue, kwargs)
        assert replay.get("status") == "success" and await evidence(container, scope, job) == first
        assert await metrics() == observed
    STAGE = "paid_retire_only_test_runtime"
    await archive_sources(container, scope, job)
    await retire_test_runtime(container, scope)
    async with container.infra.pg_connector.get_session_context() as db:
        remaining = set(
            (
                await db.execute(
                    text(
                        "SELECT id FROM profile.user_launch "
                        "WHERE type='CHAT' AND status='PROCESSING'"
                    )
                )
            ).scalars()
        )
    assert remaining == old_jobs
    return {
        "paid_harness_verified": True,
        "model": paid_model(),
        "job_id": str(job),
        "thread_id": str(scope.thread_id),
        "credits": first["credits"],
        "tokens": first["tokens"],
        "reserved": first["reserved"],
        "preflight_estimate": estimate,
        "rounds": first["rounds"],
        "commands": first["commands"],
        "provider_requests": observed["paid_completions"],
        "denied_catalog_reads": observed["blocked_requests"],
        "charges": 1,
        "test_runtime_removed": True,
        "journal_and_snapshots_preserved": True,
    }


async def main():
    async with paid_environment() as container, backend_http(container):
        outcome = await exercise(container)
    print(json.dumps(outcome))


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
