"""Owned prefork worker on a disposable broker, never the permanent agents queue."""

import asyncio
import json
import os
import signal
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path


@asynccontextmanager
async def prefork_worker(database, queue, *, additional_queues=()):
    from service.infrastructure.messaging.celery_app import celery_app

    hostname = queue + "@acceptance"
    provider_env = {}
    if os.environ.get("HARNESS_ACCEPTANCE_SCENARIO") in {"read_change", "question_change"}:
        selected = os.environ["HARNESS_ACCEPTANCE_PROVIDER"]
        provider_env = {
            "AGENTS__LLM_PROVIDER": selected,
            "AGENTS__PROVIDER_ENABLED": json.dumps(
                {
                    name: name == selected
                    for name in ("gigachat", "routerai", "openai", "openrouter", "mws", "local")
                }
            ),
        }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "scripts.harness.live.worker_entry",
            "-A",
            "service.infrastructure.messaging.celery_app",
            "worker",
            "--pool=prefork",
            "--concurrency=1",
            "--queues=" + ",".join((queue, *additional_queues)),
            "--hostname=" + hostname,
            "--loglevel=CRITICAL",
            "--without-gossip",
            "--without-mingle",
            "--without-heartbeat",
        ],
        env={
            **os.environ,
            **provider_env,
            "PG__DB": database,
            "PYTHONPATH": os.pathsep.join(
                (str(Path(__file__).resolve().parents[3]), os.environ.get("PYTHONPATH", ""))
            ),
            "AGENTS__ENGINE_MODE": "http",
            "AGENTS__SIDECAR_URL": "http://agents:8091",
            "AGENTS__WORKSPACE_URL": "http://workspace:8082",
            "IDE_CHECKPOINTS__ENABLED": "true",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    from scripts.harness.live.worker_entry import forward_diagnostics

    diagnostics = asyncio.create_task(asyncio.to_thread(forward_diagnostics, process.stdout))
    try:
        async with asyncio.timeout(40):
            while True:
                assert process.poll() is None, "acceptance_worker_stopped"
                replies = await asyncio.to_thread(
                    celery_app.control.ping, destination=[hostname], timeout=1
                )
                if replies:
                    break
                await asyncio.sleep(0.2)
        yield celery_app, process.pid
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.to_thread(process.wait, 30)
            except subprocess.TimeoutExpired:
                # Only this owned worker group, never a workspace/container.
                os.killpg(process.pid, signal.SIGKILL)
                await asyncio.to_thread(process.wait, 10)
        await diagnostics


async def deliver(app, queue, kwargs, *, task_id=None, timeout=160):
    handle = app.send_task(
        "service.services.chat.infrastructure.chat_worker_tasks.process_agent_message",
        queue=queue,
        kwargs=kwargs,
        **({"task_id": task_id} if task_id else {}),
    )
    try:
        async with asyncio.timeout(timeout):
            while not await asyncio.to_thread(handle.ready):
                await asyncio.sleep(0.2)
        result = await asyncio.to_thread(handle.get, timeout=5, propagate=False)
        from scripts.harness.live.delivery_diagnostics import delivery_diagnostic

        if diagnostic := delivery_diagnostic(result):
            print(json.dumps(diagnostic), flush=True)
        return result
    except TimeoutError:
        print('{"stage":"worker_delivery","delivery_status":"timeout"}', flush=True)
        raise
    finally:
        if await asyncio.to_thread(handle.ready):
            await asyncio.to_thread(handle.forget)
