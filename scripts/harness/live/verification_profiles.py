"""Actual framework/output receipts; no fabricated process result or completion evidence."""

import asyncio
import json
import logging
import sys
import traceback
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text

from scripts.harness.live.command import admit, prepare
from scripts.harness.live.environment import backend_http, environment

CASES = {
    "unittest_pass": (
        "import unittest\nclass Check(unittest.TestCase):\n"
        "    def test_result(self): self.assertEqual(2 + 2, 4)\n",
        "unittest",
        "passed",
        "",
    ),
    "unittest_fail": (
        "import unittest\nclass Check(unittest.TestCase):\n"
        "    def test_result(self): self.assertEqual(2 + 2, 5)\n",
        "unittest",
        "failed",
        "verification_failed",
    ),
    "empty": ("# No tests\n", "unittest", "blocked", "empty_test_suite"),
    "skipped": (
        "import unittest\nclass Check(unittest.TestCase):\n"
        "    @unittest.skip('not executable')\n    def test_result(self): pass\n",
        "unittest",
        "blocked",
        "empty_test_suite",
    ),
    "pytest_missing": (
        "def test_result(): assert True\n",
        "pytest",
        "blocked",
        "runtime_unavailable",
    ),
    "pytest_pass": ("def test_result(): assert 2 + 2 == 4\n", "pytest", "passed", ""),
    "pytest_fail": (
        "def test_result(): assert 2 + 2 == 5\n",
        "pytest",
        "failed",
        "verification_failed",
    ),
    "pytest_empty": ("# Проверок нет\n", "pytest", "blocked", "empty_test_suite"),
    "pytest_skipped": (
        "import pytest\n@pytest.mark.skip(reason='Проверка пропущена')\ndef test_result(): pass\n",
        "pytest",
        "blocked",
        "empty_test_suite",
    ),
    "stdout_extra": ("print('hello world\\n')\n", "python_script", "failed", "unexpected_output"),
    "truncated": ("print('x' * 200000)\n", "python_script", "blocked", "output_unavailable"),
}
STAGE = "verification_environment"


async def exercise(container, case):
    global STAGE
    from service.services.chat.application.harness_capability import issue

    content, profile, expected_status, expected_reason = CASES[case]
    STAGE = "verification_prepare_project"
    scope, generation = await prepare(container, content=content)
    owner = await admit(container, scope, generation)
    operation = str(uuid4())
    spec = {
        "profile": profile,
        "target": "hello_world.py",
        "criterion_id": "verify_project",
        "timeout_sec": 10,
    }
    if profile == "python_script":
        spec["expected_stdout"] = "hello world\n"
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8002",
        timeout=60,
        headers={"Authorization": "Bearer " + issue(owner)},
    ) as client:

        async def exchange(body):
            response = await client.post("/internal/harness/v1/exchange", json=body)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "private, no-store"
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
        STAGE = "verification_run_and_observe"
        response = await client.post(
            "/internal/harness/v1/commands",
            json={
                "action": "run",
                "operation_id": operation,
                "spec": spec,
            },
        )
        assert response.status_code == 200
        command = response.json()["command"]
        async with asyncio.timeout(40):
            while command["state"] not in {"completed", "failed", "cancelled"}:
                await asyncio.sleep(0.1)
                response = await client.post(
                    "/internal/harness/v1/commands",
                    json={
                        "action": "status",
                        "operation_id": operation,
                    },
                )
                assert response.status_code == 200
                command = response.json()["command"]
        STAGE = "verification_assert_executor_receipt"
        assert command["state"] == ("completed" if expected_status == "passed" else "failed")
        assert command["verification"]["status"] == expected_status
        assert command["verification"]["reason"] == expected_reason
        assert command["final_revision"]
        if case == "pytest_missing":
            assert command["result"]["exit_code"] == 127
        if case == "pytest_pass":
            assert command["result"]["exit_code"] == 0
        if case == "pytest_fail":
            assert command["result"]["exit_code"] == 1
        if case == "truncated":
            assert command["result"]["truncated"] is True
        if case in {"empty", "skipped"}:
            assert command["result"]["exit_code"] == 0
        replay = await client.post(
            "/internal/harness/v1/commands",
            json={
                "action": "run",
                "operation_id": operation,
                "spec": spec,
            },
        )
        assert replay.status_code == 200 and replay.json()["command"] == command
        snapshot = (await exchange({"opcode": "state"}))["snapshot"]["state"]
        facts = [item for item in snapshot["evidence"] if item["criterion_id"] == "verify_project"]
        assert len(facts) == 1
        assert (
            facts[0]["outcome"]
            == {
                "passed": "passed",
                "failed": "failed",
                "blocked": "unknown",
            }[expected_status]
        )
        assert (
            facts[0]["source_revision"] == snapshot["source_revision"] == command["final_revision"]
        )
        completion = (await exchange({"opcode": "result"}))["result"]
        assert completion["status"] != "completed" and "script" in completion["unchecked"]
    async with container.infra.pg_connector.get_session_context() as db:
        saved = await db.scalar(
            text("SELECT command FROM profile.harness_operation WHERE operation_id=:operation"),
            {"operation": UUID(operation)},
        )
        assert saved["cleanup_confirmed"] is True
        assert saved["output_complete"] is (case != "truncated")
        assert (
            await db.scalar(
                text(
                    "SELECT sum(command_pins) FROM profile.ide_checkpoint_intent "
                    "WHERE repository_id=:repo"
                ),
                {"repo": scope.repository_id},
            )
            == 0
        )
    return {"verification_profile_verified": case, "replay_unchanged": True}


async def main(case):
    assert case in CASES
    async with environment() as container, backend_http(container):
        result = await exercise(container, case)
    print(json.dumps({**result, "fixture_data_removed": True}))


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(main(sys.argv[-1]))
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
