"""Private transport cannot postpone checkpoints until the whole audit finishes."""

import asyncio
import copy
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from service.infrastructure.agents_client.document_audit import client as document_audit
from service.infrastructure.agents_client.document_audit.stream import (
    CHECKPOINT_KEY,
    RESULT_KEY,
    consume_audit_frames,
)
from service.infrastructure.sidecar import SidecarClient, SidecarError


def journal(attempt):
    return {
        "schema_version": 1,
        "attempt_id": str(attempt),
        "revision": 1,
        "receipts": [
            {
                "receipt_id": "fixture-call",
                "provider": "gigachat",
                "model": "GigaChat-2-Max",
                "kind": "document_visual_audit",
                "prompt": 30,
                "completion": 3,
                "estimated": False,
            }
        ],
    }


async def frames(values):
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_first_http_frame_does_not_wait_for_terminal_or_large_buffer():
    release = asyncio.Event()
    closed = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"checkpoint":{}}\n'
            await release.wait()
            yield b'{"result":{}}\n'

        async def aclose(self):
            closed.append(True)

    client = SidecarClient(
        service="agents",
        base_url="http://fixture",
        timeout=2,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "application/x-ndjson"},
                stream=Body(),
            )
        ),
    )
    stream = client.request_ndjson("POST", "/document-audit", json_body={})
    try:
        async with asyncio.timeout(0.2):
            assert await anext(stream) == {"checkpoint": {}}
    finally:
        release.set()
        await stream.aclose()
    assert closed == [True]


@pytest.mark.asyncio
async def test_consumer_awaits_persistence_before_reading_terminal():
    attempt = uuid4()
    committed = []

    async def source():
        yield {CHECKPOINT_KEY: journal(attempt)}
        assert committed == [True]
        yield {RESULT_KEY: {"status": "failed"}}

    async def persist(payload):
        assert payload == journal(attempt)
        await asyncio.sleep(0)
        committed.append(True)

    result = await consume_audit_frames(source(), attempt_id=attempt, persist=persist)
    assert result == {"status": "failed"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["wrong_attempt", "wrong_kind", "regression", "duplicate_result", "unknown", "missing"]
)
async def test_invalid_private_protocol_never_accepts_terminal(fault):
    attempt = uuid4()
    payload = journal(attempt)
    sequence = [{CHECKPOINT_KEY: payload}, {RESULT_KEY: {"status": "passed"}}]
    if fault == "wrong_attempt":
        payload["attempt_id"] = str(uuid4())
    elif fault == "wrong_kind":
        payload["receipts"][0]["kind"] = "chat"
    elif fault == "regression":
        changed = copy.deepcopy(payload)
        changed["receipts"][0]["prompt"] = 31
        sequence.insert(1, {CHECKPOINT_KEY: changed})
    elif fault == "duplicate_result":
        sequence.append(sequence[-1])
    elif fault == "unknown":
        sequence = [{"provider-body-marker": "private"}]
    else:
        sequence.pop()

    async def persist(_):
        pass

    with pytest.raises(SidecarError) as raised:
        await consume_audit_frames(frames(sequence), attempt_id=attempt, persist=persist)
    assert str(raised.value) == "agents: protocol"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"[]\n", b'{"a":1}', b"\n", b'{"a":"' + b"x" * 80 + b'"}\n'])
async def test_http_parser_rejects_unbounded_or_malformed_frames(body):
    client = SidecarClient(
        service="agents",
        base_url="http://fixture",
        timeout=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "application/x-ndjson"}, content=body
            )
        ),
    )
    with pytest.raises(SidecarError):
        async for _ in client.request_ndjson(
            "POST", "/document-audit", json_body={}, max_frame_bytes=64
        ):
            pass


@pytest.mark.asyncio
async def test_checkpoint_commit_failure_never_reads_terminal():
    attempt = uuid4()
    terminal_read = []

    async def source():
        yield {CHECKPOINT_KEY: journal(attempt)}
        terminal_read.append(True)
        yield {RESULT_KEY: {"status": "passed"}}

    async def persist(_):
        raise RuntimeError("bounded-commit-failure")

    with pytest.raises(RuntimeError, match="bounded-commit-failure"):
        await consume_audit_frames(source(), attempt_id=attempt, persist=persist)
    assert not terminal_read


@pytest.mark.asyncio
async def test_opt_in_client_uses_bound_attempt_and_existing_outcome_adapter(monkeypatch):
    attempt = uuid4()
    persisted = []
    closed = []
    monkeypatch.setattr(document_audit.provider_policy, "disabled_providers", lambda: ())
    monkeypatch.setattr(
        document_audit.provider_policy, "blocked_providers", AsyncMock(return_value=())
    )

    async def request(self, method, path, *, json_body):
        assert method == "POST" and path == "/document-audit/v2"
        assert json_body["checkpoint_attempt_id"] == str(attempt)
        try:
            yield {CHECKPOINT_KEY: journal(attempt)}
            yield {
                RESULT_KEY: {
                    "status": "failed",
                    "passed": False,
                    "retryable": False,
                    "usage": {"calls": journal(attempt)["receipts"]},
                }
            }
        finally:
            closed.append(True)

    async def persist(value):
        persisted.append(value)

    monkeypatch.setattr(SidecarClient, "request_ndjson", request)
    result = await document_audit.audit_document(
        object(),
        workspace_ref={},
        build_id="fixture-build",
        checkpoint_attempt_id=attempt,
        checkpoint_sink=persist,
        fresh_attempt=True,
    )
    assert result["status"] == "failed" and result["usage"]["total"] == 33
    assert persisted == [journal(attempt)] and closed == [True]
