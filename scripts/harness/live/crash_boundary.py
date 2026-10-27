"""Kill only an owned prefork child after a real committed write checkpoint."""

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import get_args

from service.shared.harness_protocol import Exchange

_OPCODES = frozenset(get_args(Exchange.model_fields["opcode"].annotation))
_MAX_DIAGNOSTIC_BYTES = 2 * 1048576


def _diagnostic_object(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _capture(target, chunk):
    target.extend(chunk[: max(0, _MAX_DIAGNOSTIC_BYTES - len(target))])


def kill_owned_child(pid, parent, database):
    assert type(pid) is int and pid > 1 and pid != parent
    process = Path("/proc") / str(pid)
    descriptor = os.pidfd_open(pid)
    try:
        stat = (process / "stat").read_text().rsplit(")", 1)[1].split()
        environment = (process / "environ").read_bytes().split(b"\0")
        assert int(stat[1]) == parent and os.getpgid(pid) == parent
        assert ("PG__DB=" + database).encode() in environment
        assert any(
            item.startswith(b"CELERY__BROKER_URL=redis://gpthub-harness-broker-")
            for item in environment
        )
        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
    finally:
        os.close(descriptor)


class CrashAfterWrite:
    def __init__(self, boundary="checkpoint"):
        assert boundary in {"checkpoint", "provider_receipt"}
        self.mode = boundary
        self.job_id = None
        self.callback = None
        self.count = 0
        self.boundary = None
        self.task = None
        self.replayed_grants = []
        self.responses = []

    def matches(self, payload):
        if self.mode == "provider_receipt":
            receipt = payload.get("receipt") or {}
            calls = (receipt.get("message") or {}).get("tool_calls") or []
            return (
                not self.count
                and self.callback is not None
                and payload.get("opcode") == "call_receipt"
                and self.job_id is not None
                and receipt.get("status") == "succeeded"
                and any(
                    (call.get("function") or {}).get("name") == "ide_run_command" for call in calls
                )
            )
        state = payload.get("state") or {}
        return (
            not self.count
            and self.callback is not None
            and payload.get("opcode") == "checkpoint"
            and (state.get("contract") or {}).get("task_id") == self.job_id
            and (payload.get("continuation") or {}).get("phase") == "model"
            and any(item.get("kind") == "file" for item in state.get("evidence", []))
        )


class CrashBoundaryMiddleware:
    def __init__(self, app, fault):
        self.app, self.fault = app, fault

    async def __call__(self, scope, receive, send):
        if scope.get("path") != "/internal/harness/v1/exchange":
            return await self.app(scope, receive, send)
        body = bytearray()
        response_body = bytearray()
        response_status = None

        async def observed_receive():
            message = await receive()
            _capture(body, message.get("body", b""))
            return message

        async def observed_send(message):
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
            elif message["type"] == "http.response.body":
                _capture(response_body, message.get("body", b""))
            if message["type"] == "http.response.start" and message["status"] == 200:
                payload = _diagnostic_object(body)
                if self.fault.matches(payload):
                    self.fault.count += 1
                    self.fault.boundary = payload
                    self.fault.task = asyncio.create_task(self.fault.callback())
                    await asyncio.shield(self.fault.task)
            await send(message)

        await self.app(scope, observed_receive, observed_send)
        payload = _diagnostic_object(body)
        result = _diagnostic_object(response_body)
        detail = result.get("detail") if isinstance(result, dict) else None
        code = detail.get("code") if isinstance(detail, dict) else None
        allowed = {
            "harness_fenced",
            "checkpoint_unavailable",
            "checkpoint_conflict",
            "budget_unavailable",
            "budget_exhausted",
            "usage_limit_exceeded",
            "provider_state_incompatible",
            "operation_conflict",
            "operation_unknown",
            "task_contract_invalid",
            "cancelled",
            "binding_changed",
            "cost_unknown",
        }
        opcode = payload.get("opcode")
        self.fault.responses.append(
            {
                "opcode": opcode if isinstance(opcode, str) and opcode in _OPCODES else None,
                "status": response_status,
                "code": code if code in allowed else None,
            }
        )
        del self.fault.responses[:-128]
        if response_status == 200 and self.fault.replayed_grants is not None:
            from scripts.harness.live.replay import observe_replay

            observe_replay(self.fault, payload, result)
