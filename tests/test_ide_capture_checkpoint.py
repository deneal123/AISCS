import asyncio
import io
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.infrastructure.ide.transports.capture import CapturePolicy, RepositoryCapture
from service.services.chat.application.ide.checkpoints.capture import capture_checkpoint
from service.services.chat.application.workspace_collaboration import CollaborationError
from service.services.chat.domain.ide.checkpoints.blob import IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.revision import CheckpointRecord
from service.services.chat.domain.ide.edits import IdeEditError
from service.services.chat.domain.ide.runtime import (
    ResolvedRuntime,
    RuntimeAttempt,
    WorkspaceBinding,
    generation_tag,
)
from tests.test_ide_checkpoint_revisions import BODY
from tests.test_ide_checkpoint_revisions import setup as setup

LIMITS = CapturePolicy(16, 128, 256, 1000, 512, 8)


@pytest.fixture
def capture_setup(setup, monkeypatch):
    scope, intent, repository, storage, service = setup
    repository.get_owned.return_value = None
    expires = int(time.time()) + 60
    resolved = ResolvedRuntime(
        RuntimeAttempt(intent.allocation_id, expires, "ready", 1),
        WorkspaceBinding("a" * 32, "PRIVATE", expires),
    )
    store = SimpleNamespace(preflight=AsyncMock())
    calls, streams = [], []

    @asynccontextmanager
    async def capture(user, binding, **kwargs):
        calls.append((user, binding, kwargs))
        with io.BytesIO(BODY) as source:
            streams.append(source)
            yield RepositoryCapture(source, intent.blob.size, intent.blob.sha256)

    edits = SimpleNamespace(
        _context=AsyncMock(return_value=(resolved, "PRIVATE_CAP", store)),
        _current=AsyncMock(),
        runtime=SimpleNamespace(client=SimpleNamespace(capture=capture)),
    )
    monkeypatch.setattr(
        "service.services.chat.application.ide.checkpoints.capture.verify_capability",
        lambda raw: raw,
    )
    args = dict(
        checkpoint_id=intent.blob.checkpoint_id,
        base_checkpoint_id=None,
        generation=generation_tag(resolved.attempt),
        session="s" * 16,
        limits=LIMITS,
    )
    return scope, intent, repository, storage, service, edits, store, calls, streams, args


@pytest.mark.asyncio
async def test_generation_admitted_capture_reaches_verified_blob_and_existing_head_cas(
    capture_setup,
):
    scope, intent, repository, storage, service, edits, store, calls, streams, args = capture_setup
    result = await capture_checkpoint(edits, service, scope, **args)
    assert result.is_current and result.state == "published"
    assert len(calls) == 1 and calls[0][0] == scope.user_id
    assert calls[0][2] == dict(capability="PRIVATE_CAP", limits=LIMITS)
    assert store.preflight.await_count == 2 and edits._current.await_count == 2
    assert streams[0].closed
    async with storage.open(scope, intent.blob) as saved:
        assert saved.read() == BODY
    repository.reserve.assert_awaited_once_with(intent)
    repository.publish.assert_awaited_once_with(scope, intent.blob.checkpoint_id, verified=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["before_capture", "after_capture", "coordination"])
async def test_stale_generation_or_coordination_failure_never_uploads(capture_setup, failure):
    scope, _, repository, _, service, edits, store, calls, streams, args = capture_setup
    if failure == "before_capture":
        edits._current.side_effect = IdeEditError("ide_generation_changed")
    if failure == "after_capture":
        edits._current.side_effect = [None, IdeEditError("ide_generation_changed")]
    if failure == "coordination":
        store.preflight.side_effect = CollaborationError("PRIVATE")
    with pytest.raises((IdeEditError, IdeCheckpointError)):
        await capture_checkpoint(edits, service, scope, **args)
    repository.reserve.assert_not_awaited()
    repository.publish.assert_not_awaited()
    if streams:
        assert streams[0].closed
    assert len(calls) == (1 if failure == "after_capture" else 0)


@pytest.mark.asyncio
async def test_existing_published_intent_is_replayed_without_runtime_or_capture(capture_setup):
    scope, intent, repository, _, service, edits, _, calls, _, args = capture_setup
    repository.get_owned.return_value = CheckpointRecord(
        intent, "published", intent.blob.checkpoint_id
    )
    result = await capture_checkpoint(edits, service, scope, **args)
    assert result.is_current and calls == []
    edits._context.assert_not_awaited()
    repository.reserve.assert_not_awaited()
    repository.publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [dict(base_checkpoint_id=uuid4()), dict(generation="b" * 64)])
async def test_replay_cannot_reinterpret_an_old_intent(capture_setup, change):
    scope, intent, repository, _, service, edits, _, calls, _, args = capture_setup
    repository.get_owned.return_value = CheckpointRecord(intent, "pending", None)
    with pytest.raises(IdeCheckpointError, match="ide_checkpoint_intent_mismatch"):
        await capture_checkpoint(edits, service, scope, **{**args, **change})
    assert not calls
    edits._context.assert_not_awaited()
    repository.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_during_capture_never_reserves_or_publishes(capture_setup):
    scope, _, repository, _, service, edits, _, _, _, args = capture_setup

    @asynccontextmanager
    async def capture(*args, **kwargs):
        raise asyncio.CancelledError
        yield

    edits.runtime.client.capture = capture
    with pytest.raises(asyncio.CancelledError):
        await capture_checkpoint(edits, service, scope, **args)
    repository.reserve.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_intent_reconciles_its_original_blob_without_recapture(capture_setup):
    scope, intent, repository, storage, service, edits, _, calls, _, args = capture_setup
    await storage.put(scope, intent.blob, io.BytesIO(BODY))
    repository.get_owned.return_value = CheckpointRecord(intent, "pending", None)
    result = await capture_checkpoint(edits, service, scope, **args)
    assert result.is_current and calls == []
    edits._context.assert_not_awaited()
    repository.reserve.assert_not_awaited()
    repository.publish.assert_awaited_once_with(scope, intent.blob.checkpoint_id, verified=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["alive", "expired", "replaced"])
async def test_lost_writer_receipt_can_publish_verified_bytes_without_runtime_or_new_upload(
    capture_setup, runtime
):
    scope, intent, repository, storage, service, edits, _, calls, _, args = capture_setup
    await storage.put(scope, intent.blob, io.BytesIO(BODY))
    repository.get_owned.return_value = CheckpointRecord(intent, "pending", None)
    repository.mark_upload_settled = AsyncMock()
    repository.publish.return_value = CheckpointRecord(
        intent,
        "published",
        intent.blob.checkpoint_id if runtime == "alive" else uuid4(),
        upload_settled=False,
    )
    service.historical = True
    storage.put = AsyncMock(side_effect=AssertionError("unexpected_reupload"))
    # A retired runtime must not prevent recovery of an already persisted intent.
    edits._context.side_effect = IdeEditError("ide_generation_changed")
    result = await capture_checkpoint(edits, service, scope, **args)
    assert result.state == "published" and result.is_current is (runtime == "alive")
    assert not result.upload_settled
    assert calls == []
    edits._context.assert_not_awaited()
    repository.reserve.assert_not_awaited()
    repository.mark_upload_settled.assert_not_awaited()
    storage.put.assert_not_awaited()
    repository.publish.assert_awaited_once_with(
        scope, intent.blob.checkpoint_id, verified=True, historical=True
    )


@pytest.mark.asyncio
async def test_storage_identity_changed_during_capture_cannot_publish_to_another_backend(
    capture_setup,
):
    scope, _, repository, storage, service, edits, store, _, streams, args = capture_setup

    async def preflight(*a, **kw):
        if store.preflight.await_count == 2:
            storage.storage = SimpleNamespace(namespace_id="0" * 64)

    store.preflight.side_effect = preflight
    with pytest.raises(IdeCheckpointError, match="ide_checkpoint_storage_changed"):
        await capture_checkpoint(edits, service, scope, **args)
    repository.reserve.assert_not_awaited()
    assert streams[0].closed
