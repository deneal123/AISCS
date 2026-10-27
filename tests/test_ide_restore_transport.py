import asyncio
import hashlib
import io
import json
import threading
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest

from service.infrastructure.ide.transports.capture import CapturePolicy
from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.runtime import RepositoryScope
from tests.test_ide_workspace_client import attempt, binding, settings

BODY = b"private binary capsule fixture\x00\xff"
LIMITS = CapturePolicy(128, 1024 * 1024, 4 * 1024 * 1024, 8 * 1024 * 1024, 8192, 16)
pytestmark = pytest.mark.asyncio


def identity(body=BODY):
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    value = CheckpointBlob(scope, uuid4(), hashlib.sha256(body).hexdigest(), len(body))
    return scope, attempt(), value


def reply(value, blob):
    return json_reply(
        200, {**binding(value), "restore_snapshot": {"size": blob.size, "sha256": blob.sha256}}
    )


class ReplyStream(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body, self.closed = body, False

    async def __aiter__(self):
        yield self.body

    async def aclose(self):
        self.closed = True


def json_reply(status, body):
    raw = json.dumps(body).encode()
    return httpx.Response(
        status,
        stream=ReplyStream(raw),
        headers={
            "content-type": "application/json",
            "content-length": str(len(raw)),
            "cache-control": "no-store",
        },
    )


async def test_upload_streams_exact_owned_snapshot_without_redirect_retry_or_source_close():
    body = BODY * 50000
    scope, value, blob = identity(body)
    reads, calls = [], []

    class Source(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            assert size == 65536
            return super().read(size)

    async def handle(request):
        calls.append(request.url.path)
        metadata = json.loads(request.headers["x-ide-restore-request"])
        assert metadata == {
            "user_id": str(scope.user_id),
            "allocation": {
                "allocation_id": str(value.allocation_id),
                "expires_at": value.expires_at,
            },
            "snapshot": {"sha256": blob.sha256, "size": len(body)},
            "limits": {key: getattr(LIMITS, key) for key in LIMITS.__slots__},
        }
        assert request.headers["authorization"] == "Bearer PRIVATE_KEY"
        assert request.headers["accept-encoding"] == "identity"
        assert request.headers["content-length"] == str(len(body))
        assert await request.aread() == body
        return reply(value, blob)

    source = Source(body)
    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    observed = await client.restore(scope, value, blob, source=source, limits=LIMITS)
    assert observed.state == "ready" and observed.binding.workspace_id == "a" * 32
    assert calls == ["/workspaces/allocations/restore"] and len(reads) > 10
    assert not source.closed


async def test_passive_lookup_has_no_capsule_or_limits_and_cannot_allocate():
    scope, value, blob = identity()
    calls = []

    async def handle(request):
        calls.append(request.url.path)
        assert await request.aread() == b""
        metadata = json.loads(request.headers["x-ide-restore-request"])
        assert set(metadata) == {"user_id", "allocation", "snapshot"}
        return reply(value, blob)

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    assert (await client.restore(scope, value, blob)).state == "ready"
    assert calls == ["/workspaces/allocations/restore/lookup"]


@pytest.mark.parametrize(
    "code,status,state",
    [
        ("workspace_not_found", 404, "unavailable"),
        ("workspace_allocation_conflict", 409, "unavailable"),
        ("workspace_allocation_pending", 409, "pending"),
        ("workspace_allocation_expired", 410, "expired"),
        ("quota_exceeded", 413, "unavailable"),
        ("driver_failed", 502, "unavailable"),
    ],
)
async def test_uncertain_or_rejected_lookup_never_uploads_or_rearms(code, status, state, caplog):
    scope, value, blob = identity()
    calls = []

    def handle(request):
        calls.append(request.url.path)
        return json_reply(status, {"error": code, "detail": "PRIVATE_BODY"})

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    observed = await client.restore(scope, value, blob)
    assert observed.state == state and not observed.retry_allowed
    assert calls == ["/workspaces/allocations/restore/lookup"]
    assert "PRIVATE_BODY" not in caplog.text and "PRIVATE_KEY" not in caplog.text


@pytest.mark.parametrize("case", ["short", "long", "digest"])
async def test_changed_source_is_not_confirmed_and_its_borrowed_handle_stays_owned(case):
    scope, value, blob = identity()
    body = BODY[:-1] if case == "short" else BODY + b"x" if case == "long" else b"x" * len(BODY)
    calls = []

    async def handle(request):
        calls.append(request.url.path)
        await request.aread()
        return reply(value, blob)

    source = io.BytesIO(body)
    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    with pytest.raises(IdeCheckpointError, match="ide_checkpoint_integrity_failed"):
        await client.restore(scope, value, blob, source=source, limits=LIMITS)
    assert not source.closed and len(calls) <= 1


@pytest.mark.parametrize("case", ["foreign", "live", "limits", "size"])
async def test_scope_and_fresh_dispatch_admission_precede_source_or_http(case):
    scope, value, blob = identity()
    source = io.BytesIO(BODY)
    limits = LIMITS
    if case == "foreign":
        scope = replace(scope, user_id=uuid4())
    if case == "live":
        value = replace(value, state="ready")
    if case == "limits":
        limits = None
    if case == "size":
        blob = replace(blob, size=LIMITS.archive_bytes + 1)
    calls = []
    client = IdeWorkspaceClient(
        settings(), transport=httpx.MockTransport(lambda request: calls.append(request))
    )
    with pytest.raises(IdeCheckpointError):
        await client.restore(scope, value, blob, source=source, limits=limits)
    assert not calls and source.tell() == 0 and not source.closed


@pytest.mark.parametrize("change", ["missing", "different", "binding"])
async def test_ready_requires_the_exact_selected_receipt_and_allocation(change):
    scope, value, blob = identity()

    def handle(request):
        body = {**binding(value), "restore_snapshot": {"sha256": blob.sha256, "size": blob.size}}
        if change == "missing":
            del body["restore_snapshot"]
        if change == "different":
            body["restore_snapshot"]["sha256"] = "a" * 64
        if change == "binding":
            body["expires_at"] += 1
        return json_reply(200, body)

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    if change == "binding":
        assert (await client.restore(scope, value, blob)).state == "unavailable"
    else:
        with pytest.raises(IdeCheckpointError, match="ide_checkpoint_integrity_failed"):
            await client.restore(scope, value, blob)


@pytest.mark.parametrize(
    "failure",
    [
        "declared_limit",
        "stream_limit",
        "length",
        "encoding",
        "type",
        "json",
        "array",
        "redirect",
        "transport",
        "timeout",
        "cached",
    ],
)
async def test_upload_reply_is_bounded_closed_and_never_followed_or_replayed(failure, caplog):
    scope, value, blob = identity()
    calls, streams = [], []

    def handle(request):
        calls.append(request.url.path)
        if failure == "transport":
            raise httpx.ConnectError("PRIVATE_RESPONSE")
        if failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE_RESPONSE")
        raw = json.dumps(
            {**binding(value), "restore_snapshot": {"size": blob.size, "sha256": blob.sha256}}
        ).encode()
        headers = {
            "content-type": "application/json",
            "content-length": str(len(raw)),
            "cache-control": "no-store",
        }
        status = 200
        if failure == "declared_limit":
            headers["content-length"] = "20000"
        if failure == "stream_limit":
            raw = b"x" * 20000
            del headers["content-length"]
        if failure == "length":
            headers["content-length"] = str(len(raw) + 1)
        if failure == "encoding":
            headers["content-encoding"] = "gzip"
        if failure == "type":
            headers["content-type"] = "text/html"
        if failure == "json":
            raw = b"PRIVATE_RESPONSE"
            headers["content-length"] = str(len(raw))
        if failure == "array":
            raw = b"[]"
            headers["content-length"] = "2"
        if failure == "redirect":
            status = 302
            headers["location"] = "https://invalid.example/PRIVATE_RESPONSE"
        if failure == "cached":
            del headers["cache-control"]
        stream = ReplyStream(raw)
        streams.append(stream)
        return httpx.Response(status, stream=stream, headers=headers)

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    assert (await client.restore(scope, value, blob)).state == "unavailable"
    assert calls == ["/workspaces/allocations/restore/lookup"]
    assert all(stream.closed for stream in streams)
    assert "PRIVATE_RESPONSE" not in caplog.text and "PRIVATE_KEY" not in caplog.text


async def test_boolean_size_is_not_the_selected_single_byte_receipt():
    scope, value, blob = identity(b"x")

    def handle(request):
        return json_reply(
            200, {**binding(value), "restore_snapshot": {"size": True, "sha256": blob.sha256}}
        )

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    with pytest.raises(IdeCheckpointError, match="ide_checkpoint_integrity_failed"):
        await client.restore(scope, value, blob)


@pytest.mark.parametrize("expired", [True, False])
async def test_expiry_or_disabled_transport_does_not_borrow_source_or_dispatch(expired):
    scope, value, blob = identity()
    calls = []
    client = IdeWorkspaceClient(
        settings(), transport=httpx.MockTransport(lambda request: calls.append(request))
    )
    if expired:
        value = replace(value, expires_at=1)
    else:
        client.enabled = False
    source = io.BytesIO(BODY)
    observed = await client.restore(scope, value, blob, source=source, limits=LIMITS)
    assert observed.state == ("expired" if expired else "unavailable")
    assert not calls and source.tell() == 0 and not source.closed


async def test_cancellation_waits_for_borrowed_file_read_before_returning_to_storage_owner():
    scope, value, blob = identity()
    entered, release = threading.Event(), threading.Event()

    class Source(io.BytesIO):
        def read(self, size=-1):
            entered.set()
            assert release.wait(2)
            assert not self.closed
            return super().read(size)

    async def handle(request):
        await request.aread()
        return reply(value, blob)

    source = Source(BODY)
    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    task = asyncio.create_task(client.restore(scope, value, blob, source=source, limits=LIMITS))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not source.closed
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not source.closed


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ReadError])
async def test_lost_upload_ack_is_unknown_and_only_explicit_same_identity_lookup_recovers(error):
    scope, value, blob = identity()
    calls = []

    async def handle(request):
        calls.append(request.url.path)
        metadata = json.loads(request.headers["x-ide-restore-request"])
        assert metadata["allocation"]["allocation_id"] == str(value.allocation_id)
        assert metadata["snapshot"] == {"sha256": blob.sha256, "size": blob.size}
        if request.url.path.endswith("/restore"):
            assert await request.aread() == BODY
            raise error("PRIVATE_RESPONSE")
        assert await request.aread() == b""
        return reply(value, blob)

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    source = io.BytesIO(BODY)
    assert (
        await client.restore(scope, value, blob, source=source, limits=LIMITS)
    ).state == "unavailable"
    assert calls == ["/workspaces/allocations/restore"]
    assert (await client.restore(scope, value, blob)).state == "ready"
    assert calls == ["/workspaces/allocations/restore", "/workspaces/allocations/restore/lookup"]
    assert not source.closed


async def test_expiry_during_upload_cannot_return_ready_even_after_a_positive_reply(monkeypatch):
    scope, value, blob = identity()

    async def handle(request):
        await request.aread()
        monkeypatch.setattr(
            "service.infrastructure.ide.transports.restore.time.time", lambda: value.expires_at + 1
        )
        return reply(value, blob)

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    observed = await client.restore(scope, value, blob, source=io.BytesIO(BODY), limits=LIMITS)
    assert observed.state == "expired" and observed.binding is None
