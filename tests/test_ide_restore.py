"""Private coordinator boundaries: no repeated upload after any uncertain ACK."""

import asyncio
import io
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.infrastructure.ide.transports.capture import CapturePolicy
from service.services.chat.application.ide.checkpoints.restore import IdeRestoreService
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.restore import RestoreRecord, RestoreReservation
from service.services.chat.domain.ide.checkpoints.revision import CheckpointIntent, CheckpointRecord
from service.services.chat.domain.ide.runtime import (
    RepositoryScope,
    RuntimeObservation,
    WorkspaceBinding,
)
from service.shared.repositories.exceptions import RepositoryOperationalError

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fixture():
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    blob = CheckpointBlob(scope, uuid4(), "a" * 64, 10)
    record = RestoreRecord(
        uuid4(), blob, uuid4(), uuid4(), int(time.time()) + 300, "b" * 64, "pending"
    )
    saved = CheckpointRecord(
        CheckpointIntent(blob, record.base_allocation_id, None, record.storage_namespace),
        "published",
        blob.checkpoint_id,
    )
    events, source = [], io.BytesIO(b"0123456789")

    @asynccontextmanager
    async def opened(*_args):
        events.append("open")
        try:
            yield saved, source
        finally:
            events.append("closed")

    async def claim(*_args, **_kwargs):
        events.append("committed")
        return RestoreReservation(record, True)

    async def uploaded(*_args, **kwargs):
        events.append("upload" if "source" in kwargs else "lookup")
        return RuntimeObservation("ready", WorkspaceBinding("c" * 32, "SECRET", record.expires_at))

    repository = SimpleNamespace(
        get_owned=AsyncMock(return_value=None),
        reserve=AsyncMock(side_effect=claim),
        publish=AsyncMock(return_value=replace(record, state="published")),
    )
    checkpoints = SimpleNamespace(
        status=AsyncMock(return_value=saved),
        open_saved=Mock(side_effect=opened),
        storage=SimpleNamespace(namespace=record.storage_namespace),
    )
    client = SimpleNamespace(
        allocation_ttl=AsyncMock(return_value=300), restore=AsyncMock(side_effect=uploaded)
    )
    limits = CapturePolicy(128, 1024, 4096, 8192, 1024, 16)
    service = IdeRestoreService(repository, checkpoints, client, limits=limits)
    return SimpleNamespace(**locals())


async def restore(f):
    return await f.service.restore(
        f.scope, f.record.restore_id, f.blob.checkpoint_id, f.record.base_allocation_id
    )


async def test_claim_commits_before_open_and_upload_then_only_receipt_can_publish(fixture):
    f = fixture
    outcome = await restore(f)
    assert outcome.state == "published"
    assert f.events == ["committed", "open", "upload", "closed"]
    args, kwargs = f.client.restore.await_args
    assert args == (f.scope, f.record.attempt(dispatch=True), f.blob)
    assert kwargs == {"source": f.source, "limits": f.limits}
    f.repository.publish.assert_awaited_once_with(f.scope, f.record.restore_id, verified=True)
    assert not f.source.closed  # actual open_saved owns closing, not the borrowed transport


@pytest.mark.parametrize("visible", [True, False])
async def test_lost_claim_commit_ack_never_opens_bytes_or_dispatches(fixture, visible):
    f = fixture
    f.repository.reserve.side_effect = RepositoryOperationalError()
    f.repository.get_owned.side_effect = [None, f.record if visible else None]
    if visible:
        assert await restore(f) == f.record
    else:
        with pytest.raises(IdeCheckpointError, match="ide_checkpoint_status_unknown"):
            await restore(f)
    f.checkpoints.open_saved.assert_not_called()
    f.client.restore.assert_not_awaited()
    f.repository.publish.assert_not_awaited()


@pytest.mark.parametrize("state", ["pending", "published", "expired", "conflict"])
async def test_exact_replay_never_preflights_or_uploads_and_only_pending_looks_up(fixture, state):
    f = fixture
    f.repository.get_owned.return_value = replace(f.record, state=state)
    result = await restore(f)
    assert result.state == ("published" if state == "pending" else state)
    assert f.events == (["lookup"] if state == "pending" else [])
    f.client.allocation_ttl.assert_not_awaited()
    f.checkpoints.status.assert_not_awaited()
    f.checkpoints.open_saved.assert_not_called()
    f.repository.reserve.assert_not_awaited()


@pytest.mark.parametrize("field", ["checkpoint_id", "base_allocation_id"])
async def test_replay_payload_change_is_rejected_before_any_native_lookup(fixture, field):
    f = fixture
    f.repository.get_owned.return_value = f.record
    args = [f.scope, f.record.restore_id, f.blob.checkpoint_id, f.record.base_allocation_id]
    args[2 if field == "checkpoint_id" else 3] = uuid4()
    with pytest.raises(IdeCheckpointError, match="ide_checkpoint_intent_mismatch"):
        await f.service.restore(*args)
    f.client.restore.assert_not_awaited()
    f.repository.reserve.assert_not_awaited()


@pytest.mark.parametrize("state", ["pending", "unknown", "unavailable", "expired", "rejected"])
async def test_non_ready_native_reply_never_promotes_runtime_or_repeats_upload(fixture, state):
    f = fixture
    f.client.restore.side_effect = None
    f.client.restore.return_value = RuntimeObservation(state)
    f.repository.publish.return_value = f.record
    assert await restore(f) == f.record
    assert f.client.restore.await_count == 1
    f.repository.publish.assert_awaited_once_with(f.scope, f.record.restore_id, verified=False)


async def test_lost_upload_ack_can_only_be_reconciled_explicitly(fixture):
    f = fixture
    f.client.restore.side_effect = None
    f.client.restore.return_value = RuntimeObservation("unavailable")
    f.repository.publish.return_value = f.record
    assert await restore(f) == f.record
    assert f.client.restore.await_count == 1
    f.repository.get_owned.return_value = f.record
    f.client.restore.return_value = RuntimeObservation(
        "ready", WorkspaceBinding("c" * 32, "SECRET", f.record.expires_at)
    )
    f.repository.publish.return_value = replace(f.record, state="published")
    assert (await f.service.reconcile(f.scope, f.record.restore_id)).state == "published"
    args, kwargs = f.client.restore.await_args
    assert args == (f.scope, f.record.attempt(), f.blob) and not kwargs
    assert f.checkpoints.open_saved.call_count == 1


@pytest.mark.parametrize("error", [None, RepositoryOperationalError()])
async def test_unknown_ownership_cannot_dispatch(fixture, error):
    f = fixture
    if error:
        f.repository.get_owned.side_effect = error
    else:
        f.checkpoints.status.side_effect = IdeRepositoryNotFound()
    with pytest.raises(IdeCheckpointError if error else IdeRepositoryNotFound):
        await restore(f)
    f.repository.reserve.assert_not_awaited()
    f.client.restore.assert_not_awaited()


@pytest.mark.parametrize("kind", ["namespace", "unpublished", "policy", "ttl"])
async def test_preflight_failure_cannot_reserve_or_open_bytes(fixture, kind):
    f = fixture
    if kind == "namespace":
        f.checkpoints.storage.namespace = "d" * 64
    if kind == "unpublished":
        f.checkpoints.status.return_value = replace(f.saved, state="pending")
    if kind == "policy":
        f.service.limits = CapturePolicy(1, 1, 1, 1, 1, 1)
    if kind == "ttl":
        f.client.allocation_ttl.return_value = None
    with pytest.raises(IdeCheckpointError):
        await restore(f)
    f.repository.reserve.assert_not_awaited()
    f.checkpoints.open_saved.assert_not_called()


async def test_expired_reconciliation_does_not_contact_native_or_open_storage(fixture):
    f = fixture
    f.repository.get_owned.return_value = replace(f.record, expires_at=1)
    f.repository.publish.return_value = replace(f.record, expires_at=1, state="expired")
    assert (await f.service.reconcile(f.scope, f.record.restore_id)).state == "expired"
    f.client.restore.assert_not_awaited()
    f.checkpoints.open_saved.assert_not_called()
    f.repository.publish.assert_awaited_once_with(f.scope, f.record.restore_id, verified=False)


async def test_lost_publish_ack_reads_exact_journal_and_never_dispatches_again(fixture):
    f = fixture
    f.repository.get_owned.side_effect = [None, replace(f.record, state="published")]
    f.repository.publish.side_effect = RepositoryOperationalError()
    assert (await restore(f)).state == "published"
    assert f.client.restore.await_count == 1
    assert f.checkpoints.open_saved.call_count == 1


async def test_cancelled_upload_closes_storage_context_without_publication_or_retry(fixture):
    f = fixture
    f.client.restore.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await restore(f)
    assert f.events == ["committed", "open", "closed"]
    f.repository.publish.assert_not_awaited()
    assert f.checkpoints.open_saved.call_count == 1
    assert f.client.restore.await_count == 1


async def test_wrong_deadline_binding_cannot_publish(fixture):
    f = fixture
    f.client.restore.side_effect = None
    f.client.restore.return_value = RuntimeObservation(
        "ready", WorkspaceBinding("c" * 32, "SECRET", f.record.expires_at + 1)
    )
    f.repository.publish.return_value = f.record
    assert await restore(f) == f.record
    f.repository.publish.assert_awaited_once_with(f.scope, f.record.restore_id, verified=False)


@pytest.mark.parametrize("lost_ack", [False, True])
@pytest.mark.parametrize(
    "field",
    [
        "restore_id",
        "base_allocation_id",
        "allocation_id",
        "expires_at",
        "storage_namespace",
        "blob",
    ],
)
async def test_publication_and_uncertain_readback_cannot_change_frozen_restore_identity(
    fixture, field, lost_ack
):
    f = fixture
    replacement = (
        f.record.expires_at + 1
        if field == "expires_at"
        else "d" * 64
        if field == "storage_namespace"
        else replace(f.blob, sha256="d" * 64)
        if field == "blob"
        else uuid4()
    )
    changed = replace(f.record, **{field: replacement, "state": "published"})
    if lost_ack:
        f.repository.publish.side_effect = RepositoryOperationalError()
        f.repository.get_owned.side_effect = [None, changed]
    else:
        f.repository.publish.return_value = changed
    with pytest.raises(IdeCheckpointError, match="ide_checkpoint_intent_mismatch"):
        await restore(f)
    assert f.client.restore.await_count == 1
    assert f.checkpoints.open_saved.call_count == 1
