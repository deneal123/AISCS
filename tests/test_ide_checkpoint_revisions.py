"""Publication orchestration; real SQL concurrency is exercised separately."""

import asyncio
import hashlib
import io
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.services.chat.application.ide.checkpoints.service import IdeCheckpointService
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.budget import CheckpointStorageBudget
from service.services.chat.domain.ide.checkpoints.revision import (
    CheckpointIntent,
    CheckpointRecord,
    CheckpointReservation,
)
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.shared.repositories.exceptions import RepositoryOperationalError

BODY = b"synthetic-repository-bundle\0\xff"


@pytest.fixture
def setup(tmp_path):
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    blob = CheckpointBlob(scope, uuid4(), hashlib.sha256(BODY).hexdigest(), len(BODY))
    storage = IdeCheckpointStorage(LocalFileStorage(tmp_path), max_bytes=1000)
    intent = CheckpointIntent(blob, uuid4(), None, storage.namespace)
    pending = CheckpointRecord(intent, "pending", None)
    published = CheckpointRecord(intent, "published", blob.checkpoint_id)
    repository = MagicMock(
        reserve=AsyncMock(return_value=CheckpointReservation(pending, True)),
        publish=AsyncMock(return_value=published),
        get_owned=AsyncMock(return_value=pending),
    )
    return scope, intent, repository, storage, IdeCheckpointService(repository, storage)


@pytest.mark.asyncio
async def test_durable_claim_then_verified_object_then_atomic_head(setup):
    scope, intent, repository, storage, service = setup
    order = []
    original = storage.put

    async def reserve(value):
        assert value == intent
        order.append("claim_committed")
        return CheckpointReservation(CheckpointRecord(intent, "pending", None), True)

    async def put(*args):
        assert order == ["claim_committed"]
        await original(*args)
        order.append("object_verified")

    async def publish(*args, **kwargs):
        assert order == ["claim_committed", "object_verified"]
        assert kwargs == {"verified": True}
        order.append("head_committed")
        return CheckpointRecord(intent, "published", intent.blob.checkpoint_id)

    repository.reserve.side_effect = reserve
    repository.publish.side_effect = publish
    storage.put = put
    result = await service.save(scope, intent, io.BytesIO(BODY))
    assert result.state == "published" and result.is_current
    assert order == ["claim_committed", "object_verified", "head_committed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("current", [True, False])
async def test_retention_follows_only_confirmed_current_publication(setup, current):
    scope, intent, repository, _, service = setup
    retention = MagicMock(run=AsyncMock())
    service.retention = retention
    repository.publish.return_value = CheckpointRecord(
        intent, "published", intent.blob.checkpoint_id if current else uuid4()
    )
    await service.save(scope, intent, io.BytesIO(BODY))
    if current:
        retention.run.assert_awaited_once_with(scope, intent.blob.checkpoint_id)
    else:
        retention.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_error_does_not_turn_published_save_into_failure(setup):
    scope, intent, repository, _, service = setup
    service.retention = MagicMock(run=AsyncMock(side_effect=IdeCheckpointError()))
    assert (await service.save(scope, intent, io.BytesIO(BODY))).is_current
    repository.reserve.assert_awaited_once()


@pytest.mark.asyncio
async def test_budgeted_upload_records_settlement_before_publication(setup):
    scope, intent, repository, _, service = setup
    service.budget = CheckpointStorageBudget(1000, 100, 2)
    repository.mark_upload_settled = AsyncMock(
        return_value=CheckpointRecord(intent, "pending", None, upload_settled=True)
    )
    await service.save(scope, intent, io.BytesIO(BODY))
    repository.reserve.assert_awaited_once_with(intent, budget=service.budget)
    repository.mark_upload_settled.assert_awaited_once_with(intent)
    repository.publish.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_revoked_attempt_collects_only_after_its_actual_writer_settles(setup, failure):
    scope, intent, repository, storage, service = setup
    service.budget = CheckpointStorageBudget(1000, 100, 2)
    service.historical = True
    retired = CheckpointRecord(intent, "retired", None, upload_settled=True)
    repository.mark_upload_settled = AsyncMock(return_value=retired)
    repository.publish.return_value = retired
    service.retention = MagicMock(collect_record=AsyncMock(), run=AsyncMock())
    if failure:
        storage.put = AsyncMock(
            side_effect=IdeCheckpointError("ide_checkpoint_storage_unavailable")
        )
        with pytest.raises(IdeCheckpointError, match="ide_checkpoint_storage_unavailable"):
            await service.save(scope, intent, io.BytesIO(BODY))
        repository.publish.assert_not_awaited()
    else:
        assert (await service.save(scope, intent, io.BytesIO(BODY))).state == "retired"
    repository.mark_upload_settled.assert_awaited_once_with(intent)
    service.retention.collect_record.assert_awaited_once_with(scope, retired)
    service.retention.run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["failed", "cancelled", "lost_receipt"])
async def test_unsettled_or_failed_upload_never_frees_quota_or_repeats_upload(setup, outcome):
    scope, intent, repository, storage, service = setup
    service.budget = CheckpointStorageBudget(1000, 100, 2)
    repository.mark_upload_settled = AsyncMock(
        return_value=CheckpointRecord(intent, "pending", None, upload_settled=True)
    )
    if outcome == "lost_receipt":
        repository.mark_upload_settled.side_effect = RepositoryOperationalError("private db")
        assert (await service.save(scope, intent, io.BytesIO(BODY))).state == "pending"
    else:
        error = asyncio.CancelledError() if outcome == "cancelled" else IdeCheckpointError()
        storage.put = AsyncMock(side_effect=error)
        with pytest.raises(type(error)):
            await service.save(scope, intent, io.BytesIO(BODY))
        storage.put.assert_awaited_once()
    repository.mark_upload_settled.assert_awaited_once_with(intent)
    repository.publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,code",
    [
        ("quota", "ide_checkpoint_quota_exceeded"),
        ("pending", "ide_checkpoint_pending"),
        ("head_changed", "ide_checkpoint_head_changed"),
    ],
)
async def test_storage_admission_errors_do_not_dispatch_upload(setup, failure, code):
    scope, intent, repository, storage, service = setup
    service.budget = CheckpointStorageBudget(1000, 100, 2)
    repository.reserve.return_value = CheckpointReservation(failure=failure)
    storage.put = AsyncMock()
    with pytest.raises(IdeCheckpointError, match=code):
        await service.save(scope, intent, io.BytesIO(BODY))
    storage.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_recovery_keeps_verified_superseded_bytes_without_reupload_or_head_rollback(
    setup,
):
    scope, intent, repository, storage, service = setup
    await storage.put(scope, intent.blob, io.BytesIO(BODY))
    storage.put = AsyncMock()
    service.historical = True
    current = uuid4()
    repository.get_owned.return_value = CheckpointRecord(intent, "pending", current)
    repository.publish.return_value = CheckpointRecord(intent, "published", current)
    service.retention = MagicMock(run=AsyncMock())
    result = await service.reconcile(scope, intent.blob.checkpoint_id)
    assert result.state == "published" and not result.is_current
    repository.publish.assert_awaited_once_with(
        scope, intent.blob.checkpoint_id, verified=True, historical=True
    )
    repository.reserve.assert_not_awaited()
    storage.put.assert_not_awaited()
    service.retention.run.assert_awaited_once_with(scope, intent.blob.checkpoint_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", [False, True])
async def test_public_historical_mode_never_publishes_missing_or_unverified_bytes(setup, corrupt):
    scope, intent, repository, storage, service = setup
    service.historical = True
    repository.get_owned.return_value = CheckpointRecord(intent, "pending", uuid4())
    if corrupt:
        await storage.storage.upload_file(file_key=intent.blob.key_for(scope), file_data=b"wrong")
    with pytest.raises(IdeCheckpointError):
        await service.reconcile(scope, intent.blob.checkpoint_id)
    repository.publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["user_id", "thread_id", "repository_id"])
async def test_foreign_scope_never_reaches_database_or_storage(setup, changed):
    scope, intent, repository, storage, service = setup
    storage.put = AsyncMock()
    with pytest.raises(IdeCheckpointError, match="ide_checkpoint_scope_forbidden"):
        await service.save(replace(scope, **{changed: uuid4()}), intent, io.BytesIO(BODY))
    repository.reserve.assert_not_awaited()
    storage.put.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "runtime_not_ready"])
async def test_no_owned_live_generation_cannot_upload(setup, failure):
    scope, intent, repository, storage, service = setup
    repository.reserve.return_value = CheckpointReservation(failure=failure)
    storage.put = AsyncMock()
    with pytest.raises(IdeRepositoryNotFound if failure == "missing" else IdeCheckpointError):
        await service.save(scope, intent, io.BytesIO(BODY))
    storage.put.assert_not_awaited()
    repository.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_quota_rejects_before_creating_intent(setup):
    scope, intent, repository, storage, service = setup
    storage.max_bytes = 0
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_invalid$"):
        await service.save(scope, intent, io.BytesIO(BODY))
    repository.reserve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["digest", "size", "allocation", "base", "storage"])
async def test_intent_payload_is_immutable_even_after_a_replay(setup, changed):
    scope, intent, repository, storage, service = setup
    other = (
        replace(intent, blob=replace(intent.blob, sha256="a" * 64))
        if changed == "digest"
        else replace(intent, blob=replace(intent.blob, size=1))
        if changed == "size"
        else replace(intent, allocation_id=uuid4())
        if changed == "allocation"
        else replace(intent, storage_namespace="b" * 64)
        if changed == "storage"
        else replace(intent, base_checkpoint_id=uuid4())
    )
    repository.reserve.return_value = CheckpointReservation(
        CheckpointRecord(other, "pending", None)
    )
    storage.put = AsyncMock()
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_intent_mismatch$"):
        await service.save(scope, intent, io.BytesIO(BODY))
    storage.put.assert_not_awaited()
    repository.publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["save", "open_saved", "reconcile"])
async def test_another_storage_namespace_cannot_silently_supply_the_copy(
    setup, tmp_path, operation
):
    scope, intent, repository, _, _ = setup
    other = IdeCheckpointStorage(LocalFileStorage(tmp_path / "other-store"), max_bytes=1000)
    service = IdeCheckpointService(repository, other)
    # Even a same-key/same-content object in the new backend is not the original
    # storage namespace. Configuration migration is an explicit future workflow.
    await other.put(scope, intent.blob, io.BytesIO(BODY))
    if operation == "open_saved":
        repository.get_owned.return_value = CheckpointRecord(
            intent, "published", intent.blob.checkpoint_id
        )
    other.open = MagicMock()
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_storage_changed$"):
        if operation == "save":
            await service.save(scope, intent, io.BytesIO(BODY))
        elif operation == "open_saved":
            async with service.open_saved(scope, intent.blob.checkpoint_id):
                pytest.fail("wrong namespace exposed")
        else:
            await service.reconcile(scope, intent.blob.checkpoint_id)
    other.open.assert_not_called()
    repository.reserve.assert_not_awaited()
    repository.publish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["published", "conflict", "retired"])
async def test_terminal_replay_is_not_upload_or_head_rollback(setup, state):
    scope, intent, repository, storage, service = setup
    historical = CheckpointRecord(intent, state, uuid4())
    repository.reserve.return_value = CheckpointReservation(historical)
    repository.get_owned.return_value = historical
    storage.put = AsyncMock()
    storage.open = MagicMock()
    assert await service.save(scope, intent, io.BytesIO(BODY)) == historical
    assert not historical.is_current
    storage.put.assert_not_awaited()
    storage.open.assert_not_called()
    repository.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_passive_status_never_touches_blob_or_runtime(setup):
    scope, intent, repository, storage, service = setup
    storage.put = AsyncMock()
    storage.open = MagicMock()
    result = await service.status(scope, intent.blob.checkpoint_id)
    assert result.state == "pending"
    repository.reserve.assert_not_awaited()
    repository.publish.assert_not_awaited()
    storage.put.assert_not_awaited()
    storage.open.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [IdeCheckpointError, asyncio.CancelledError])
async def test_failed_or_cancelled_object_cannot_publish_or_delete(setup, failure):
    scope, intent, repository, storage, service = setup
    storage.put = AsyncMock(side_effect=failure())
    storage.storage.delete_file = AsyncMock()
    with pytest.raises(failure):
        await service.save(scope, intent, io.BytesIO(BODY))
    repository.publish.assert_not_awaited()
    storage.storage.delete_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_lost_publish_ack_resolves_through_exact_owned_status(setup):
    scope, intent, repository, _, service = setup
    repository.publish.side_effect = RepositoryOperationalError("PRIVATE_DB_MARKER")
    repository.get_owned.return_value = CheckpointRecord(
        intent, "published", intent.blob.checkpoint_id
    )
    result = await service.save(scope, intent, io.BytesIO(BODY))
    assert result.is_current
    repository.get_owned.assert_awaited_once_with(scope, intent.blob.checkpoint_id)
    repository.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_lost_ack_cannot_claim_a_historical_publication_is_still_current(setup):
    scope, intent, repository, _, service = setup
    repository.publish.side_effect = RepositoryOperationalError()
    repository.get_owned.return_value = CheckpointRecord(intent, "published", uuid4())
    result = await service.save(scope, intent, io.BytesIO(BODY))
    assert result.state == "published" and not result.is_current
    repository.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_lost_claim_ack_cannot_dispatch_even_when_pending_row_is_visible(setup):
    scope, intent, repository, storage, service = setup
    repository.reserve.side_effect = RepositoryOperationalError("PRIVATE_DB_MARKER")
    storage.put = AsyncMock()
    result = await service.save(scope, intent, io.BytesIO(BODY))
    assert result.state == "pending" and not result.is_current
    repository.publish.assert_not_awaited()
    storage.put.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [True, False])
async def test_unresolved_commit_never_becomes_success_or_reupload(setup, missing, caplog):
    scope, intent, repository, storage, service = setup
    repository.reserve.side_effect = RepositoryOperationalError("PRIVATE_DB_MARKER")
    repository.get_owned.side_effect = (
        None if missing else RepositoryOperationalError("PRIVATE_DB_MARKER")
    )
    repository.get_owned.return_value = None
    storage.put = AsyncMock()
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_status_unknown$"):
        await service.save(scope, intent, io.BytesIO(BODY))
    storage.put.assert_not_awaited()
    repository.publish.assert_not_awaited()
    assert "PRIVATE_DB_MARKER" not in caplog.text


@pytest.mark.asyncio
async def test_explicit_reconcile_verifies_stored_bytes_without_reupload(setup):
    scope, intent, repository, storage, service = setup
    # The upload survived but no metadata publication was acknowledged.
    await storage.put(scope, intent.blob, io.BytesIO(BODY))
    storage.put = AsyncMock()
    result = await service.reconcile(scope, intent.blob.checkpoint_id)
    assert result.is_current
    storage.put.assert_not_awaited()
    repository.publish.assert_awaited_once_with(scope, intent.blob.checkpoint_id, verified=True)


@pytest.mark.asyncio
async def test_missing_object_leaves_pending_metadata_for_reconciliation(setup):
    scope, intent, repository, storage, service = setup
    storage.put = AsyncMock()
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_storage_unavailable$"):
        await service.reconcile(scope, intent.blob.checkpoint_id)
    repository.publish.assert_not_awaited()
    repository.reserve.assert_not_awaited()
    storage.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_superseded_pending_intent_does_not_wait_for_a_missing_object(setup):
    scope, intent, repository, storage, service = setup
    newer = uuid4()
    repository.get_owned.return_value = CheckpointRecord(intent, "pending", newer)
    repository.publish.return_value = CheckpointRecord(intent, "conflict", newer)
    storage.open = MagicMock()
    assert (await service.reconcile(scope, intent.blob.checkpoint_id)).state == "conflict"
    storage.open.assert_not_called()
    repository.publish.assert_awaited_once_with(scope, intent.blob.checkpoint_id, verified=False)


@pytest.mark.asyncio
async def test_deleted_repo_during_upload_does_not_publish_or_delete_orphan(setup):
    scope, intent, repository, storage, service = setup
    repository.publish.return_value = None
    storage.storage.delete_file = AsyncMock()
    with pytest.raises(IdeRepositoryNotFound):
        await service.save(scope, intent, io.BytesIO(BODY))
    storage.storage.delete_file.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "conflict", "retired"])
async def test_only_published_metadata_allows_reading_a_saved_revision(setup, state):
    scope, intent, repository, storage, service = setup
    repository.get_owned.return_value = CheckpointRecord(intent, state, None)
    storage.open = MagicMock()
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_not_published$"):
        async with service.open_saved(scope, intent.blob.checkpoint_id):
            pytest.fail("unpublished copy exposed")
    storage.open.assert_not_called()


@pytest.mark.asyncio
async def test_selected_published_copy_is_not_retargeted_when_head_moves(setup):
    scope, intent, repository, storage, service = setup
    await storage.put(scope, intent.blob, io.BytesIO(BODY))
    repository.get_owned.side_effect = [
        CheckpointRecord(intent, "published", intent.blob.checkpoint_id),
        CheckpointRecord(intent, "published", uuid4()),
    ]
    async with service.open_saved(scope, intent.blob.checkpoint_id) as (record, source):
        assert source.read() == BODY
        assert not record.is_current
        assert record.intent == intent
    assert source.closed
    repository.reserve.assert_not_awaited()
    repository.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_deleted_owner_during_download_cannot_expose_saved_source(setup):
    scope, intent, repository, storage, service = setup
    await storage.put(scope, intent.blob, io.BytesIO(BODY))
    repository.get_owned.side_effect = [
        CheckpointRecord(intent, "published", intent.blob.checkpoint_id),
        None,
    ]
    with pytest.raises(IdeRepositoryNotFound):
        async with service.open_saved(scope, intent.blob.checkpoint_id):
            pytest.fail("revoked source exposed")


@pytest.mark.parametrize(
    "change",
    [
        {"allocation_id": "bad"},
        {"base_checkpoint_id": "bad"},
        {"blob": None},
        {"storage_namespace": None},
        {"storage_namespace": "A" * 64},
    ],
)
def test_invalid_intent_is_not_a_publication_command(change):
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    intent = CheckpointIntent(CheckpointBlob(scope, uuid4(), "0" * 64, 0), uuid4(), None, "b" * 64)
    with pytest.raises(IdeCheckpointError):
        replace(intent, **change)
    with pytest.raises(IdeCheckpointError):
        replace(intent, base_checkpoint_id=intent.blob.checkpoint_id)
