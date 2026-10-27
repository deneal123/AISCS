"""Private checkpoints precede terminal JSON without becoming public events."""

import asyncio
import json
from uuid import uuid4

import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.presentation.routers.agent.usage_checkpoint import USAGE_KEY
from service.presentation.routers.capabilities import document_audit as endpoint
from service.presentation.routers.capabilities.audit_usage_stream import (
    RESULT_KEY,
    stream_audit_usage,
)


def test_boot_identity_covers_stream_and_reused_checkpoint_contract():
    from pathlib import Path

    from service.domain.documents import runtime_digest
    from service.presentation.routers.agent import usage_checkpoint
    from service.presentation.routers.capabilities import audit_usage_stream

    base = Path(runtime_digest.__file__).parent
    covered = {(base / name).resolve() for name in runtime_digest._RUNTIME_FILES}
    assert Path(audit_usage_stream.__file__).resolve() in covered
    assert Path(usage_checkpoint.__file__).resolve() in covered


def _receipt(execution, name="first", *, estimated=False):
    execution.usage.record_usage(
        {"prompt": 30, "completion": 3},
        provider="gigachat",
        model="GigaChat-2-Max",
        kind="document_visual_audit",
        receipt_id=name,
        estimated=estimated,
    )


@pytest.mark.asyncio
async def test_checkpoint_is_delivered_while_audit_is_still_running():
    release = asyncio.Event()
    attempt = str(uuid4())

    async def run():
        with use_run_execution(PrivateRunResources()) as execution:
            _receipt(execution)
            await release.wait()
            return {
                "status": "passed",
                "passed": True,
                "retryable": False,
                "usage": execution.usage.project_since(0),
            }

    stream = stream_audit_usage(attempt, run)
    async with asyncio.timeout(1):
        first = json.loads(await anext(stream))
        assert first[USAGE_KEY]["attempt_id"] == attempt
        assert first[USAGE_KEY]["receipts"][0]["receipt_id"] == "first"
        assert RESULT_KEY not in first
        release.set()
        remaining = [json.loads(frame) async for frame in stream]
    assert len(remaining) == 1 and remaining[0][RESULT_KEY]["passed"]


@pytest.mark.asyncio
async def test_coalesced_snapshot_retains_every_call_and_latest_precision():
    async def run():
        with use_run_execution(PrivateRunResources()) as execution:
            _receipt(execution, estimated=True)
            _receipt(execution, "second")
            _receipt(execution, estimated=False)
            return {"status": "failed", "passed": False, "retryable": False}

    frames = [json.loads(frame) async for frame in stream_audit_usage(str(uuid4()), run)]
    journal = frames[0][USAGE_KEY]
    assert journal["revision"] == 3
    assert [item["receipt_id"] for item in journal["receipts"]] == ["first", "second"]
    assert not journal["receipts"][0]["estimated"]
    assert RESULT_KEY in frames[-1]


@pytest.mark.asyncio
async def test_consumer_disconnect_cancels_producer_and_unsubscribes():
    cancelled = []
    ledgers = []

    async def run():
        with use_run_execution(PrivateRunResources()) as execution:
            ledgers.append(execution.usage)
            _receipt(execution)
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

    stream = stream_audit_usage(str(uuid4()), run)
    async with asyncio.timeout(1):
        await anext(stream)
        await stream.aclose()
    assert cancelled == [True]
    assert not ledgers[0]._observers


@pytest.mark.asyncio
async def test_exception_body_is_not_a_terminal_frame():
    async def run():
        with use_run_execution(PrivateRunResources()) as execution:
            _receipt(execution)
            raise RuntimeError("private-provider-body-marker")

    frames = [frame async for frame in stream_audit_usage(str(uuid4()), run)]
    assert all(b"private-provider-body-marker" not in frame for frame in frames)
    assert json.loads(frames[-1])[RESULT_KEY] == {
        "status": "internal",
        "passed": False,
        "retryable": True,
    }


@pytest.mark.asyncio
async def test_private_opt_in_reuses_auth_and_existing_audit_budget(monkeypatch):
    from service.presentation.routers.capabilities import managed_document_audit
    from tests.test_document_audit_registry import RedisFixture

    auth = []
    monkeypatch.setattr(endpoint, "internal_auth", auth.append)
    redis = RedisFixture()
    monkeypatch.setattr(managed_document_audit, "get_redis", lambda: redis)

    async def audit(_ref, _build, *, execution, usage_checkpoint=None):
        _receipt(execution)
        from types import SimpleNamespace

        return SimpleNamespace(status="failed", passed=False, retryable=False, diagnostics=())

    monkeypatch.setattr(endpoint, "audit_document_build", audit)
    response = await endpoint.audit_document(
        endpoint.DocumentAuditRequest(
            build_id="fixture-build",
            workspace_ref={"user_id": str(uuid4()), "workspace_id": "fixture-workspace"},
            checkpoint_attempt_id=uuid4(),
            fresh_attempt=True,
        ),
        authorization="fixture-auth",
    )
    assert auth == ["fixture-auth"]
    assert response.media_type == "application/x-ndjson"
    assert response.headers["cache-control"] == "no-store"
    frames = [json.loads(frame) async for frame in response.body_iterator]
    assert USAGE_KEY in frames[0] and frames[-1][RESULT_KEY]["usage"]["total"] == 33
