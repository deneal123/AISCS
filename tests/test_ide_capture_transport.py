import asyncio
import hashlib
import io
import json
import threading
import time
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest

from service.infrastructure.ide.transports.capture import CapturePolicy
from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.services.chat.domain.ide.checkpoints.blob import IdeCheckpointError
from service.services.chat.domain.ide.runtime import WorkspaceBinding
from tests.test_ide_workspace_client import settings

LIMITS = CapturePolicy(128, 1024, 4096, 8192, 2048, 16)
BODY = b"\x00\xffPK\x03\x04verified capsule bytes"


class Stream(httpx.AsyncByteStream):
    def __init__(self, body=BODY, failure=False):
        self.body, self.failure, self.closed, self.reads = body, failure, False, 0

    async def __aiter__(self):
        self.reads += 1
        yield self.body[:4]
        if self.failure:
            raise httpx.ReadError("PRIVATE_RESPONSE")
        yield self.body[4:]

    async def aclose(self):
        self.closed = True


def reply(stream, **headers):
    return httpx.Response(
        200,
        stream=stream,
        headers={
            "content-type": "application/octet-stream",
            "content-length": str(len(BODY)),
            "x-ide-capsule-version": "1",
            "x-ide-capsule-sha256": hashlib.sha256(BODY).hexdigest(),
            **headers,
        },
    )


def binding():
    return WorkspaceBinding("a" * 32, "PRIVATE_TOKEN", int(time.time()) + 60)


@pytest.mark.asyncio
async def test_capture_streams_exact_private_identity_without_retry_and_closes_resources():
    calls, stream, value, user = [], Stream(), binding(), uuid4()

    def handle(request):
        calls.append(request)
        assert request.url.path == f"/workspaces/{value.workspace_id}/ide/capture"
        assert request.headers["accept-encoding"] == "identity"
        assert request.headers["authorization"] == "Bearer PRIVATE_KEY"
        assert json.loads(request.content)["expected_expires_at"] == value.expires_at
        assert json.loads(request.content)["coordination_capability"] == "PRIVATE_CAPABILITY"
        return reply(stream)

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    async with client.capture(
        user, value, capability="PRIVATE_CAPABILITY", limits=LIMITS
    ) as capsule:
        assert capsule.source.read() == BODY
        assert capsule.size == len(BODY) and capsule.sha256 == hashlib.sha256(BODY).hexdigest()
        assert stream.closed and "PRIVATE" not in repr(capsule)
    assert capsule.source.closed and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {"content-length": "99999"},
        {"content-length": "0"},
        {"content-length": "01"},
        {"content-type": "text/html"},
        {"x-ide-capsule-version": "2"},
        {"x-ide-capsule-sha256": "wrong"},
        {"content-encoding": "gzip"},
    ],
)
async def test_bad_headers_fail_before_reading_source_without_retry(headers):
    stream, calls = Stream(), []

    def handle(request):
        calls.append(request)
        return reply(stream, **headers)

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    with pytest.raises(IdeCheckpointError):
        async with client.capture(uuid4(), binding(), capability="cap", limits=LIMITS):
            pytest.fail()
    assert len(calls) == 1 and stream.closed and stream.reads == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stream",
    [Stream(BODY[:-1]), Stream(BODY + b"x"), Stream(b"x" * len(BODY)), Stream(failure=True)],
)
async def test_partial_corrupt_or_failed_capture_never_reaches_the_consumer(stream):
    client = IdeWorkspaceClient(
        settings(), transport=httpx.MockTransport(lambda request: reply(stream))
    )
    with pytest.raises(IdeCheckpointError) as caught:
        async with client.capture(uuid4(), binding(), capability="cap", limits=LIMITS):
            pytest.fail()
    assert "PRIVATE" not in str(caught.value) and stream.closed


@pytest.mark.asyncio
async def test_consumer_failure_is_not_reclassified_as_a_capture_failure():
    stream = Stream()
    client = IdeWorkspaceClient(
        settings(), transport=httpx.MockTransport(lambda request: reply(stream))
    )
    with pytest.raises(ValueError, match="consumer"):
        async with client.capture(uuid4(), binding(), capability="cap", limits=LIMITS) as capsule:
            raise ValueError("consumer")
    assert stream.closed and capsule.source.closed


@pytest.mark.asyncio
async def test_repeated_cancellation_keeps_borrowed_spool_alive_until_native_write_settles(
    monkeypatch,
):
    started, release = threading.Event(), threading.Event()

    class SlowSource(io.BytesIO):
        def write(self, content):
            started.set()
            assert release.wait(5)
            return super().write(content)

    source, stream = SlowSource(), Stream()
    monkeypatch.setattr(
        "service.infrastructure.ide.transports.capture.SpooledTemporaryFile", lambda **kw: source
    )
    client = IdeWorkspaceClient(
        settings(), transport=httpx.MockTransport(lambda request: reply(stream))
    )

    async def capture():
        async with client.capture(uuid4(), binding(), capability="cap", limits=LIMITS):
            pytest.fail()

    task = asyncio.create_task(capture())
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not source.closed and not stream.closed
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert source.closed and stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("expired,enabled", [(True, True), (False, False)])
async def test_missing_runtime_admission_never_dispatches_capture(expired, enabled):
    calls = []

    def handle(request):
        calls.append(request)
        return reply(Stream())

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    client.enabled = enabled
    value = replace(binding(), expires_at=1) if expired else binding()
    with pytest.raises(IdeCheckpointError):
        async with client.capture(uuid4(), value, capability="cap", limits=LIMITS):
            pytest.fail()
    assert not calls
