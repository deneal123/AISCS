"""The live crash injector cannot signal an unrelated process or pre-commit task."""

import json
from unittest.mock import Mock

import pytest

from scripts.harness.live import crash_boundary


@pytest.mark.parametrize("mismatch", [None, "parent", "group", "database", "broker"])
def test_sigkill_requires_the_owned_child_and_uses_a_pinned_pidfd(monkeypatch, tmp_path, mismatch):
    pid, parent, database = 1234, 4321, "gpthub_acceptance_" + "a" * 24
    process = tmp_path / str(pid)
    process.mkdir()
    (process / "stat").write_text(
        f"{pid} (celery child) S {parent + int(mismatch == 'parent')} 0", encoding="utf-8"
    )
    environment = [
        "PG__DB=" + ("other" if mismatch == "database" else database),
        "CELERY__BROKER_URL=redis://"
        + ("other" if mismatch == "broker" else "gpthub-harness-broker-fixture"),
    ]
    (process / "environ").write_bytes("\0".join(environment).encode())
    monkeypatch.setattr(crash_boundary, "Path", lambda _: tmp_path)
    opened, closed, signalled = Mock(return_value=99), Mock(), Mock()
    monkeypatch.setattr(crash_boundary.os, "pidfd_open", opened, raising=False)
    monkeypatch.setattr(crash_boundary.os, "close", closed)
    monkeypatch.setattr(
        crash_boundary.os, "getpgid", lambda _: parent + int(mismatch == "group"), raising=False
    )
    monkeypatch.setattr(crash_boundary.signal, "pidfd_send_signal", signalled, raising=False)
    monkeypatch.setattr(crash_boundary.signal, "SIGKILL", 9, raising=False)
    if mismatch:
        with pytest.raises(AssertionError):
            crash_boundary.kill_owned_child(pid, parent, database)
        signalled.assert_not_called()
    else:
        crash_boundary.kill_owned_child(pid, parent, database)
        signalled.assert_called_once_with(99, crash_boundary.signal.SIGKILL)
    opened.assert_called_once_with(pid)
    closed.assert_called_once_with(99)


@pytest.mark.asyncio
async def test_crash_callback_occurs_once_after_a_committed_owned_file_checkpoint():
    committed, killed = [], []
    fault = crash_boundary.CrashAfterWrite()
    fault.job_id = "owned-task"
    payload = {
        "opcode": "checkpoint",
        "state": {"contract": {"task_id": fault.job_id}, "evidence": [{"kind": "file"}]},
        "continuation": {"phase": "model"},
    }

    async def kill():
        assert committed
        killed.append(True)

    async def app(scope, receive, send):
        await receive()
        committed.append(True)
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"{}"})

    async def receive():
        return {"type": "http.request", "body": json.dumps(payload).encode()}

    async def send(message):
        assert committed and killed

    fault.callback = kill
    middleware = crash_boundary.CrashBoundaryMiddleware(app, fault)
    for _ in range(2):
        await middleware({"path": "/internal/harness/v1/exchange"}, receive, send)
    assert fault.count == len(killed) == 1


def test_read_only_other_task_or_uncommitted_phase_cannot_trigger_crash():
    fault = crash_boundary.CrashAfterWrite()
    fault.job_id, fault.callback = "owned", object()
    for task, kind, phase in [
        ("other", "file", "model"),
        ("owned", "read", "model"),
        ("owned", "file", "tools"),
    ]:
        assert not fault.matches(
            {
                "opcode": "checkpoint",
                "state": {"contract": {"task_id": task}, "evidence": [{"kind": kind}]},
                "continuation": {"phase": phase},
            }
        )


def test_provider_receipt_boundary_selects_only_successful_command_planning_response():
    fault = crash_boundary.CrashAfterWrite("provider_receipt")
    fault.job_id, fault.callback = "owned", object()
    for name, status, expected in [
        ("ide_run_command", "succeeded", True),
        ("ide_write_file", "succeeded", False),
        ("submit_task_contract", "succeeded", False),
        ("ide_run_command", "unknown", False),
    ]:
        assert (
            fault.matches(
                {
                    "opcode": "call_receipt",
                    "receipt": {
                        "status": status,
                        "message": {"tool_calls": [{"function": {"name": name}}]},
                    },
                }
            )
            is expected
        )
