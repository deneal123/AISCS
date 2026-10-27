"""Public application projection and replay, before HTTP/UI composition."""

import json
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.infrastructure.ide.transports.capture import CapturePolicy
from service.services.chat.application.ide.checkpoints import saved_projects as api
from service.services.chat.application.ide.checkpoints.retention import RetentionResult
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.budget import CheckpointStorageBudget
from service.services.chat.domain.ide.checkpoints.restore import RestoreRecord
from service.services.chat.domain.ide.checkpoints.revision import CheckpointIntent, CheckpointRecord
from service.services.chat.domain.ide.runtime import RepositoryScope, RuntimeAttempt, generation_tag


@pytest.fixture
def fixture():
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    attempt = RuntimeAttempt(uuid4(), int(time.time()) + 300, "ready", 1)
    intent = CheckpointIntent(
        CheckpointBlob(scope, uuid4(), "a" * 64, 10), attempt.allocation_id, None, "b" * 64
    )
    saved = CheckpointRecord(intent, "published", intent.blob.checkpoint_id, upload_settled=True)
    runtime = SimpleNamespace(
        repository=SimpleNamespace(get_owned=AsyncMock(return_value={"name": "owned"})),
        runtime=SimpleNamespace(get_owned=AsyncMock(return_value=attempt)),
    )
    repository = SimpleNamespace(
        inventory=AsyncMock(return_value=[]),
        accounted_bytes=AsyncMock(return_value=10),
        abandon_pending=AsyncMock(),
        revoke_pending=AsyncMock(),
    )
    checkpoints = SimpleNamespace(
        historical=True,
        budget=CheckpointStorageBudget(1000, 100, 4),
        retention=SimpleNamespace(collect_record=AsyncMock(return_value=RetentionResult())),
        repository=repository,
        status=AsyncMock(return_value=saved),
        reconcile=AsyncMock(return_value=saved),
    )
    restores = SimpleNamespace(
        repository=SimpleNamespace(latest_owned=AsyncMock(return_value=None)),
        status=AsyncMock(side_effect=IdeRepositoryNotFound),
        restore=AsyncMock(),
        reconcile=AsyncMock(),
    )
    service = api.IdeSavedProjects(
        SimpleNamespace(runtime=runtime),
        checkpoints,
        restores,
        limits=CapturePolicy(10, 10, 100, 100, 10, 3),
    )
    return scope, attempt, saved, service


@pytest.mark.asyncio
async def test_save_uses_existing_capture_owner_and_never_returns_private_identity(
    fixture, monkeypatch
):
    scope, attempt, saved, service = fixture
    capture = AsyncMock(return_value=saved)
    monkeypatch.setattr(api, "capture_checkpoint", capture)
    result = await service.save(
        scope,
        checkpoint_id=saved.intent.blob.checkpoint_id,
        base_checkpoint_id=None,
        generation=generation_tag(attempt),
        session="session-value-123456",
    )
    assert result["is_current"] and result["state"] == "published"
    capture.assert_awaited_once()
    assert capture.await_args.kwargs["generation"] == generation_tag(attempt)
    assert capture.await_args.kwargs["session"] == "session-value-123456"
    text = json.dumps(result)
    for private in (str(attempt.allocation_id), "a" * 64, "b" * 64, "session-value-123456"):
        assert private not in text


@pytest.mark.asyncio
async def test_status_is_passive_and_cannot_publish_or_restore(fixture):
    scope, _, saved, service = fixture
    result = await service.status(scope, saved.intent.blob.checkpoint_id)
    assert result["state"] == "published"
    service.checkpoints.reconcile.assert_not_awaited()
    service.restores.restore.assert_not_awaited()


@pytest.mark.asyncio
async def test_abandon_revokes_without_receipt_object_io_or_quota_release(fixture):
    scope, _, saved, service = fixture
    retired = replace(saved, state="retired", current_checkpoint_id=None, upload_settled=False)
    service.checkpoints.repository.revoke_pending.return_value = (retired, True)
    result = await service.abandon(scope, retired.intent.blob.checkpoint_id)
    assert result["state"] == "retired" and not result["collected"]
    assert not result["can_discard"] and not result["can_abandon"]
    service.checkpoints.retention.collect_record.assert_not_awaited()
    service.checkpoints.repository.accounted_bytes.assert_not_awaited()
    service.checkpoints.reconcile.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_abandon_cannot_revoke_published_or_foreign_snapshot(fixture, missing):
    scope, _, saved, service = fixture
    service.checkpoints.repository.revoke_pending.return_value = (None if missing else saved, False)
    error = IdeRepositoryNotFound if missing else IdeCheckpointError
    with pytest.raises(error):
        await service.abandon(scope, saved.intent.blob.checkpoint_id)
    service.checkpoints.retention.collect_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_history_is_bounded_allowlisted_and_owns_its_runtime_generation(fixture):
    scope, attempt, saved, service = fixture
    row = {
        "checkpoint_id": saved.intent.blob.checkpoint_id,
        "state": "published",
        "size": 10,
        "current_checkpoint_id": saved.intent.blob.checkpoint_id,
        "created_at": "2026-10-18",
        "published_at": "2026-10-18",
        "token": "PRIVATE_TOKEN",
        "storage_namespace": "PRIVATE_BUCKET",
    }
    service.checkpoints.repository.inventory.return_value = [row] * 33
    result = await service.history(scope)
    assert result["truncated"] and len(result["items"]) == 32
    assert result["runtime"]["generation"] == generation_tag(attempt)
    assert result["usage"] == {"used_bytes": 10, "max_bytes": 1000, "max_snapshot_bytes": 100}
    assert "PRIVATE" not in json.dumps(result)
    service.restores.restore.assert_not_awaited()


@pytest.mark.asyncio
async def test_denied_history_never_reads_capsule_or_usage(fixture):
    scope, _, _, service = fixture
    service.edits.runtime.repository.get_owned.return_value = None
    with pytest.raises(IdeRepositoryNotFound):
        await service.history(scope)
    service.checkpoints.repository.inventory.assert_not_awaited()
    service.checkpoints.repository.accounted_bytes.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "settled", "is_head", "allowed"),
    [
        ("pending", False, False, False),
        ("pending", True, False, True),
        ("retired", True, False, True),
        ("conflict", True, False, True),
        ("published", True, False, False),
        ("retired", True, True, False),
    ],
)
async def test_history_exposes_only_settled_unpublished_cleanup_eligibility(
    fixture, state, settled, is_head, allowed
):
    scope, _, saved, service = fixture
    checkpoint_id = saved.intent.blob.checkpoint_id
    service.checkpoints.repository.inventory.return_value = [
        {
            "checkpoint_id": checkpoint_id,
            "state": state,
            "size": 10,
            "current_checkpoint_id": checkpoint_id if is_head else None,
            "created_at": "2026-10-18",
            "published_at": None,
            "upload_settled_at": "private-timestamp" if settled else None,
        }
    ]
    result = await service.history(scope)
    assert result["items"][0]["can_discard"] is allowed
    assert "private-timestamp" not in json.dumps(result)


@pytest.mark.asyncio
async def test_history_discovers_an_unfinished_restore_without_a_browser_local_pointer(fixture):
    scope, attempt, saved, service = fixture
    pending = RestoreRecord(
        uuid4(),
        saved.intent.blob,
        attempt.allocation_id,
        uuid4(),
        attempt.expires_at,
        saved.intent.storage_namespace,
        "pending",
    )
    service.restores.repository.latest_owned.return_value = pending
    result = await service.history(scope)
    assert result["last_restore"]["restore_id"] == str(pending.restore_id)
    assert result["last_restore"]["state"] == "pending"
    assert not result["last_restore"]["active"]
    assert str(pending.allocation_id) not in json.dumps(result)
    service.restores.restore.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
async def test_explicit_discard_requires_committed_quiescent_admission(fixture, allowed):
    scope, _, saved, service = fixture
    record = replace(saved, state="retired", current_checkpoint_id=None)
    service.checkpoints.repository.abandon_pending.return_value = (record, allowed)
    service.checkpoints.status.return_value = replace(record, collected=True)
    if allowed:
        assert (await service.discard(scope, record.intent.blob.checkpoint_id))["collected"]
        service.checkpoints.retention.collect_record.assert_awaited_once_with(scope, record)
    else:
        with pytest.raises(IdeCheckpointError, match="ide_checkpoint_not_discardable"):
            await service.discard(scope, record.intent.blob.checkpoint_id)
        service.checkpoints.retention.collect_record.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "generation", "expiry", "unknown"])
async def test_published_restore_is_not_assumed_to_be_current_or_ready(fixture, change):
    scope, attempt, saved, service = fixture
    target = uuid4()
    restored = RestoreRecord(
        uuid4(),
        saved.intent.blob,
        attempt.allocation_id,
        target,
        attempt.expires_at,
        saved.intent.storage_namespace,
        "published",
    )
    current = replace(attempt, allocation_id=target)
    if change == "generation":
        current = replace(current, allocation_id=uuid4())
    elif change == "expiry":
        current = replace(current, expires_at=current.expires_at + 1)
    elif change == "unknown":
        current = replace(current, state="unknown")
    service.edits.runtime.runtime.get_owned.return_value = current
    service.restores.status.side_effect = None
    service.restores.status.return_value = restored
    result = await service.restore_status(scope, restored.restore_id)
    assert result["active"] is (change == "none")
    assert result["generation"] == (generation_tag(current) if change == "none" else None)
    assert str(target) not in json.dumps(result)
    service.restores.restore.assert_not_awaited()


@pytest.mark.asyncio
async def test_restore_replay_uses_frozen_base_instead_of_current_binding(fixture):
    scope, attempt, saved, service = fixture
    restored = RestoreRecord(
        uuid4(),
        saved.intent.blob,
        attempt.allocation_id,
        uuid4(),
        attempt.expires_at,
        saved.intent.storage_namespace,
        "published",
    )
    service.restores.status.side_effect = None
    service.restores.status.return_value = restored
    service.restores.reconcile.return_value = restored
    result = await service.restore(
        scope,
        restore_id=restored.restore_id,
        checkpoint_id=saved.intent.blob.checkpoint_id,
        base_generation=generation_tag(attempt),
    )
    assert result["state"] == "published" and not result["active"]
    service.restores.restore.assert_not_awaited()
    service.restores.reconcile.assert_awaited_once_with(scope, restored.restore_id)
