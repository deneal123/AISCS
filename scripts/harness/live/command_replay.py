"""Новые operation IDs не повторяют команду с потерянным выводом после рестарта."""

import json
from uuid import uuid4


async def assert_no_new_command_after_lost_output(client, revision, spec):
    for candidate in (spec, {"profile": "shell", "command": "python3 hello_world.py"}):
        operation = str(uuid4())
        prepared = await client.post(
            "/internal/harness/v1/exchange",
            json={
                "opcode": "prepare_effect",
                "effect": {
                    "operation_id": operation,
                    "name": "ide_run_command",
                    "action": "exec",
                    "arguments": json.dumps(candidate),
                    "source_revision": revision,
                },
            },
        )
        assert prepared.status_code == 200
        dispatched = await client.post(
            "/internal/harness/v1/exchange",
            json={
                "opcode": "dispatch_effect",
                "operation_id": operation,
            },
        )
        assert dispatched.status_code == 200
        rejected = await client.post(
            "/internal/harness/v1/commands",
            json={
                "action": "run",
                "operation_id": operation,
                "spec": candidate,
            },
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "verification_unavailable"
        status = await client.post(
            "/internal/harness/v1/exchange",
            json={
                "opcode": "operation_status",
                "operation_id": operation,
                "operation_kind": "effect",
            },
        )
        assert status.status_code == 200
        observed = status.json()["operation_status"]
        assert observed["status"] == "failed" and observed["receipt"]["charged"] is False
