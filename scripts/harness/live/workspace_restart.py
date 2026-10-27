"""Lose a real workspace observer, then inspect/Stop the same Engine instance."""

import asyncio
import json
import logging
import os
import sys
import traceback
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.command import admit, prepare
from scripts.harness.live.environment import backend_http, environment

logging.disable(logging.CRITICAL)
STAGE = "environment"
SCRIPT = (
    "import pathlib, subprocess, sys, time\n"
    "counter = pathlib.Path('run_count.txt')\n"
    "counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else '1')\n"
    "subprocess.Popen([sys.executable, '-c', 'import os,time; os.setsid(); time.sleep(60)'])\n"
    "time.sleep(12)\n"
    "print('hello world')\n"
)


async def restart_observer(workspace):
    before = (await workspace.get("/__harness_acceptance__/instance")).json()
    assert (await workspace.post("/__harness_acceptance__/restart")).json() == {
        "restarting": before["instance"]
    }
    async with asyncio.timeout(20):
        while True:
            try:
                response = await workspace.get("/__harness_acceptance__/instance")
                if response.status_code == 200 and response.json() != before:
                    assert response.json()["instance"]
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)


async def exercise(container):
    global STAGE
    from service.composition.ide import build_ide_runtime
    from service.services.chat.application.harness_capability import issue
    from service.services.chat.application.ide.edits import IdeEditService
    from service.services.chat.persistence.harness.commands.repository import IdeCommandRepository
    from service.settings import config

    stop = os.environ["HARNESS_ACCEPTANCE_WORKSPACE_FAULT"] == "restart_stop"
    STAGE = "prepare_restart_project"
    scope, generation = await prepare(container, content=SCRIPT)
    owner = await admit(container, scope, generation)
    runtime = build_ide_runtime(container.infra.pg_connector)
    binding = (await runtime.resolve(scope)).binding
    operation = str(uuid4())
    spec = {
        "profile": "python_script",
        "target": "hello_world.py",
        "expected_stdout": "hello world\n",
        "timeout_sec": 30,
        "criterion_id": "verify_project",
    }
    async with (
        httpx.AsyncClient(
            base_url="http://127.0.0.1:8002",
            headers={"Authorization": "Bearer " + issue(owner)},
            timeout=55,
        ) as client,
        httpx.AsyncClient(
            base_url="http://workspace:8082",
            headers={"Authorization": "Bearer " + config.agents.workspace_api_key},
            timeout=3,
        ) as workspace,
    ):

        async def exchange(body):
            response = await client.post("/internal/harness/v1/exchange", json=body)
            assert response.status_code == 200
            return response.json()

        async def command(action, **fields):
            response = await client.post(
                "/internal/harness/v1/commands",
                json={"action": action, "operation_id": operation, **fields},
            )
            assert response.status_code == 200
            return response.json()["command"]

        await exchange(
            {
                "opcode": "seal",
                "expected_revision": 0,
                "proposal": {
                    "kind": "change",
                    "criteria": [
                        {"criterion_id": "script", "kind": "file", "target": "hello_world.py"}
                    ],
                },
            }
        )
        await exchange(
            {
                "opcode": "prepare_effect",
                "effect": {
                    "operation_id": operation,
                    "name": "ide_run_command",
                    "action": "exec",
                    "arguments": json.dumps(spec),
                    "source_revision": generation,
                },
            }
        )
        await exchange({"opcode": "dispatch_effect", "operation_id": operation})
        STAGE = "dispatch_restart_command"
        assert (await command("run", spec=spec))["state"] == "running"
        async with asyncio.timeout(8):
            while True:
                try:
                    started = await runtime.client.read(
                        scope.user_id, binding, operation="file", path="run_count.txt"
                    )
                    if started.get("content") == "1":
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.1)
        repository = IdeCommandRepository(container.infra.pg_connector)
        before = await repository.command_status(owner, UUID(operation))
        assert before.dispatch_authorized and before.supervisor and not before.cleanup_confirmed
        assert (await workspace.get("/__harness_acceptance__/workspace")).json() == {
            "lost": 0,
            "attempts": {"create": 1, "handshake": 1, "dispatch": 1},
            "operations": 1,
        }
        STAGE = "replace_workspace_observer"
        await restart_observer(workspace)
        STAGE = "observe_same_exec_without_replay"
        current = await command("stop" if stop else "status")
        async with asyncio.timeout(40):
            while current["state"] not in {"completed", "failed", "cancelled"}:
                await asyncio.sleep(0.2)
                current = await command("status")
        assert current["state"] == ("cancelled" if stop else "failed")
        assert current["result"] is None and current["verification"]["status"] == "blocked"
        if not stop:
            assert current["blocker"] == "output_unavailable"
        final = await repository.command_status(owner, UUID(operation))
        assert final.engine_id == before.engine_id and final.supervisor == before.supervisor
        assert final.cleanup_confirmed and final.final_revision and not final.output_complete
        assert await command("run", spec=spec) == current
        from scripts.harness.live.command_replay import assert_no_new_command_after_lost_output

        await assert_no_new_command_after_lost_output(client, final.final_revision, spec)
        assert (await exchange({"opcode": "result"}))["result"]["status"] != "completed"
        counter = await runtime.client.read(
            scope.user_id, binding, operation="file", path="run_count.txt"
        )
        assert counter["content"] == "1"
        assert (await workspace.get("/__harness_acceptance__/workspace")).json() == {
            "lost": 0,
            "attempts": {"create": 0, "handshake": 0, "dispatch": 0},
            "operations": 0,
        }
        edits = IdeEditService(runtime, container.infra.redis_client)
        lease = await edits.lease(
            scope,
            path="hello_world.py",
            generation=generation,
            session="harness-restart-buffer",
            action="acquire",
            fence=None,
        )
        await edits.lease(
            scope,
            path="hello_world.py",
            generation=generation,
            session="harness-restart-buffer",
            action="release",
            fence=lease["fence"],
        )
        async with container.infra.pg_connector.get_session_context() as db:
            assert (
                await db.scalar(text("SELECT sum(command_pins) FROM profile.ide_checkpoint_intent"))
                == 0
            )
    return {
        "workspace_restart_verified": True,
        "stop": stop,
        "output_verification_blocked": True,
        "command_repeated": False,
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
                        {"function": f.name, "line": f.lineno}
                        for f in traceback.extract_tb(error.__traceback__)[-4:]
                    ],
                }
            )
        )
        sys.exit(1)
