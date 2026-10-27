"""Real Celery admission, reservation, harness, effects, settlement and redelivery."""

import asyncio
import json
import logging
import os
import sys
import traceback
from uuid import uuid4

import httpx

from scripts.harness.live.environment import backend_http, environment
from scripts.harness.live.worker_assertions import evidence
from scripts.harness.live.worker_process import deliver, prefork_worker
from scripts.harness.live.worker_setup import funded_job

logging.disable(logging.CRITICAL)
STAGE = "environment"


async def exercise(container):
    global STAGE
    from service.settings import config

    assert os.environ["CELERY__BROKER_URL"].startswith("redis://gpthub-harness-broker-")
    STAGE = "prepare_empty_project"
    refine = os.environ.get("HARNESS_ACCEPTANCE_SCENARIO") == "refine"
    from scripts.harness.live.refinement import QUESTION, assert_adopted

    scope, job, before, kwargs = await funded_job(container, question=QUESTION if refine else None)
    queue = "harness-" + uuid4().hex
    STAGE = "worker_start"
    async with prefork_worker(config.pg.db, queue) as (app, first_pid):
        STAGE = "worker_first_delivery"
        result = await deliver(app, queue, kwargs)
        assert isinstance(result, dict) and result.get("status") == "success", (
            "acceptance_worker_failed"
        )
        metadata = result.get("metadata") or {}
        task_result = metadata.get("task_result") or {}
        if task_result.get("status") != "completed":
            print(
                json.dumps(
                    {
                        "stage": STAGE,
                        "task_status": task_result.get("status"),
                        "blocker": task_result.get("blocker"),
                        "insufficient_credits": metadata.get("insufficient_credits"),
                    }
                )
            )
        STAGE = "worker_receipts"
        first = await evidence(container, scope, job)
        assert before - first["balance"] == first["spent"]
        adaptation = await assert_adopted(container, job, terminal=True) if refine else None
        async with httpx.AsyncClient(
            timeout=5, headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key}
        ) as client:
            observed = (
                await client.get("http://agents:8091/__harness_acceptance__/transport")
            ).json()
            assert observed["completions"] > 0 and observed["blocked_requests"] == 0
            if not refine:
                assert observed["completions"] == 6
            else:
                assert observed["completions"] == adaptation["model_calls"]
            STAGE = "worker_duplicate_delivery"
            replay = await deliver(app, queue, kwargs)
            assert isinstance(replay, dict) and replay.get("status") == "success"
            assert await evidence(container, scope, job) == first
            after = (await client.get("http://agents:8091/__harness_acceptance__/transport")).json()
            assert after == observed
    STAGE = "worker_restart_redelivery"
    async with prefork_worker(config.pg.db, queue) as (app, restarted_pid):
        assert restarted_pid != first_pid
        replay = await deliver(app, queue, kwargs)
        assert isinstance(replay, dict) and replay.get("status") == "success"
        assert await evidence(container, scope, job) == first
        async with httpx.AsyncClient(
            timeout=5, headers={"Authorization": "Bearer " + config.agents.llm_gateway_api_key}
        ) as client:
            after = (await client.get("http://agents:8091/__harness_acceptance__/transport")).json()
            assert after == observed
    return {
        "worker_harness_verified": True,
        "redelivery_unchanged": True,
        "restart_redelivery_unchanged": True,
        "charges": 1,
        "commands": 1,
        **({"instruction_refinement_verified": True} if refine else {}),
    }


async def main():
    async with environment() as container, backend_http(container) as fault:
        result = await exercise(container)
        if os.environ.get("HARNESS_ACCEPTANCE_WORKSPACE_FAULT"):
            from scripts.harness.live.command import assert_dispatch_ack_boundary

            await assert_dispatch_ack_boundary()
        mode = os.environ.get("HARNESS_ACCEPTANCE_LOST_ACK", "")
        assert fault.count == int(bool(mode))
        result["lost_ack_reconciled"] = mode
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
