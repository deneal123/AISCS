"""Real HTTP schema refusal closes its intent; a corrected new operation can run."""

import asyncio
import json
import logging
import os
import sys
import traceback
from uuid import uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.command import admit, prepare
from scripts.harness.live.environment import backend_http, environment

logging.disable(logging.CRITICAL)
STAGE = "environment"


async def exercise(container):
    global STAGE
    from service.services.chat.application.harness_capability import issue, settings

    scope, generation = await prepare(container)
    owner = await admit(container, scope, generation)
    path = "/internal/harness/v1/commands"
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8002",
        timeout=55,
        headers={"Authorization": "Bearer " + issue(owner)},
    ) as client:

        async def exchange(body):
            response = await client.post("/internal/harness/v1/exchange", json=body)
            assert response.status_code == 200
            return response.json()

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
        spec = {
            "profile": "python_script",
            "target": "hello_world.py",
            "expected_stdout": "hello world\n",
            "criterion_id": "verify_project",
            "timeout_sec": 10,
            "command": "python hello_world.py",
        }

        async def intent(operation, arguments):
            await exchange(
                {
                    "opcode": "prepare_effect",
                    "effect": {
                        "operation_id": operation,
                        "name": "ide_run_command",
                        "action": "exec",
                        "arguments": json.dumps(arguments),
                        "source_revision": generation,
                    },
                }
            )
            await exchange({"opcode": "dispatch_effect", "operation_id": operation})

        invalid = str(uuid4())
        await intent(invalid, spec)
        STAGE = "known_invalid_command_refusal"
        for enabled in (True, False):
            os.environ["HARNESS__IDE_COMMANDS_ENABLED"] = str(enabled).lower()
            settings.cache_clear()
            response = await client.post(
                path, json={"action": "run", "operation_id": invalid, "spec": spec}
            )
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "harness_request_invalid"
        async with container.infra.pg_connector.get_session_context() as db:
            row = (
                (
                    await db.execute(
                        text(
                            "SELECT status,receipt,command FROM profile.harness_operation "
                            "WHERE operation_id=CAST(:operation AS uuid)"
                        ),
                        {"operation": invalid},
                    )
                )
                .mappings()
                .one()
            )
            assert row["status"] == "failed" and row["command"] is None
            assert row["receipt"]["charged"] is False and not row["receipt"]["evidence"]
        os.environ["HARNESS__IDE_COMMANDS_ENABLED"] = "true"
        settings.cache_clear()
        spec["command"] = None
        correct = str(uuid4())
        await intent(correct, spec)
        STAGE = "corrected_new_operation_executes"
        response = await client.post(
            path, json={"action": "run", "operation_id": correct, "spec": spec}
        )
        assert response.status_code == 200
        result = response.json()["command"]
        async with asyncio.timeout(30):
            while result["state"] not in {"completed", "failed", "cancelled"}:
                await asyncio.sleep(0.1)
                response = await client.post(
                    path, json={"action": "status", "operation_id": correct}
                )
                assert response.status_code == 200
                result = response.json()["command"]
        assert result["state"] == "completed" and result["verification"]["status"] == "passed"
        assert result["result"]["stdout"] == "hello world\n"
        assert (await exchange({"opcode": "result"}))["result"]["status"] != "completed"
    return {"invalid_arguments_reconciled": True, "corrected_operation_verified": True}


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
