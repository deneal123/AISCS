"""Owner deletion cannot authorize collecting an unsettled/pinned/foreign object."""

import hashlib
import io
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.services.chat.application.ide.checkpoints.orphans import IdeCheckpointOrphanService
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.revision import CheckpointIntent, CheckpointRecord
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.checkpoints.orphans import IdeCheckpointOrphanRepository
from service.services.chat.persistence.ide.checkpoints.repository import IdeCheckpointRepository
from service.shared.repositories.exceptions import RepositoryError, RepositoryOperationalError


@pytest.fixture
def fixture(tmp_path):
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    storage = IdeCheckpointStorage(LocalFileStorage(tmp_path), max_bytes=1000)
    body = b"orphan snapshot fixture"
    blob = CheckpointBlob(scope, uuid4(), hashlib.sha256(body).hexdigest(), len(body))
    intent = CheckpointIntent(blob, uuid4(), None, storage.namespace)
    record = CheckpointRecord(intent, "retired", None, upload_settled=True)
    repository = MagicMock(
        revoke_restore_publication=AsyncMock(return_value=0),
        retire_batch=AsyncMock(return_value=[record]),
        acknowledge_discard=AsyncMock(return_value=True),
    )
    return storage, body, record, repository


@pytest.mark.asyncio
async def test_exact_settled_orphan_delete_is_idempotent_and_releases_only_on_ack(fixture):
    storage, body, record, repository = fixture
    blob = record.intent.blob
    await storage.put(blob.scope, blob, io.BytesIO(body))
    service = IdeCheckpointOrphanService(repository, storage)
    for _ in range(2):
        result = await service.sweep()
        assert (result.examined, result.delete_acknowledged, result.pending) == (1, 1, 0)
        assert result.cursor == (blob.scope.repository_id, blob.checkpoint_id)
    repository.acknowledge_discard.assert_awaited_with(record.intent)
    assert not storage.storage._path(blob.key_for(blob.scope)).exists()


@pytest.mark.asyncio
async def test_unknown_retirement_commit_never_dispatches_delete(fixture):
    storage, _, _, repository = fixture
    repository.retire_batch.side_effect = RepositoryOperationalError("PRIVATE")
    storage.discard = AsyncMock()
    with pytest.raises(RepositoryOperationalError):
        await IdeCheckpointOrphanService(repository, storage).sweep()
    storage.discard.assert_not_awaited()
    repository.acknowledge_discard.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_restore_revocation_ack_never_dispatches_retirement_or_storage(fixture):
    storage, _, _, repository = fixture
    repository.revoke_restore_publication.side_effect = RepositoryOperationalError("PRIVATE")
    storage.discard = AsyncMock()
    with pytest.raises(RepositoryOperationalError):
        await IdeCheckpointOrphanService(repository, storage).sweep()
    repository.retire_batch.assert_not_awaited()
    storage.discard.assert_not_awaited()


@pytest.mark.asyncio
async def test_restore_revocation_keeps_private_allocation_ledger_and_requires_absent_descriptor():
    rows = MagicMock()
    rows.all.return_value = [(uuid4(),)]
    session = MagicMock(execute=AsyncMock(return_value=rows))
    count = await IdeCheckpointOrphanRepository(MagicMock()).revoke_restore_publication(
        storage_namespace="a" * 64, session=session
    )
    assert count == 1
    sql = str(session.execute.await_args.args[0])
    for guard in (
        "i.state='pending'",
        "i.storage_namespace=:namespace",
        "LIMIT :limit",
        "NOT EXISTS (SELECT 1 FROM profile.ide_repository r",
        "FOR UPDATE OF i SKIP LOCKED",
        "state='conflict'",
        "active_checkpoint_id=NULL",
    ):
        assert guard in sql
    for forbidden in (
        "allocation_id=",
        "expires_at=",
        "DELETE",
        "state='published'",
        "clock_timestamp()-",
    ):
        assert forbidden not in sql


@pytest.mark.asyncio
async def test_lost_storage_delete_ack_retries_same_key_without_releasing_accounting(fixture):
    storage, body, record, repository = fixture
    blob = record.intent.blob
    await storage.put(blob.scope, blob, io.BytesIO(body))
    discard = storage.discard

    async def lost_ack(scope, checkpoint):
        await discard(scope, checkpoint)
        raise IdeCheckpointError("ide_checkpoint_cleanup_unavailable")

    storage.discard = lost_ack
    service = IdeCheckpointOrphanService(repository, storage)
    assert (await service.sweep()).pending == 1
    assert not storage.storage._path(blob.key_for(blob.scope)).exists()
    repository.acknowledge_discard.assert_not_awaited()
    storage.discard = discard
    result = await service.sweep()
    assert result.delete_acknowledged == 1 and result.pending == 0
    repository.acknowledge_discard.assert_awaited_once_with(record.intent)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["storage", "ack_lost", "ack_denied"])
async def test_delete_failure_or_unknown_ack_never_invents_collection(fixture, failure):
    storage, _, record, repository = fixture
    storage.discard = AsyncMock()
    if failure == "storage":
        storage.discard.side_effect = IdeCheckpointError("ide_checkpoint_cleanup_unavailable")
    elif failure == "ack_lost":
        repository.acknowledge_discard.side_effect = RepositoryOperationalError("PRIVATE")
    else:
        repository.acknowledge_discard.return_value = False
    result = await IdeCheckpointOrphanService(repository, storage).sweep()
    assert result.pending == 1
    assert result.delete_acknowledged == int(failure != "storage")
    assert result.cursor == (
        record.intent.blob.scope.repository_id,
        record.intent.blob.checkpoint_id,
    )
    if failure == "storage":
        repository.acknowledge_discard.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unsettled", "published", "head", "collected", "namespace"])
async def test_application_rejects_noncollectible_records_even_if_repository_regresses(
    fixture, change
):
    storage, _, record, repository = fixture
    if change == "unsettled":
        record = replace(record, upload_settled=False)
    elif change == "published":
        record = replace(record, state="published")
    elif change == "head":
        record = replace(record, current_checkpoint_id=record.intent.blob.checkpoint_id)
    elif change == "collected":
        record = replace(record, collected=True)
    else:
        record = replace(record, intent=replace(record.intent, storage_namespace="f" * 64))
    repository.retire_batch.return_value = [record]
    storage.discard = AsyncMock()
    assert (await IdeCheckpointOrphanService(repository, storage).sweep()).pending == 1
    storage.discard.assert_not_awaited()
    repository.acknowledge_discard.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_sql_rechecks_descriptor_pin_namespace_and_exact_immutable_identity(fixture):
    storage, _, record, _ = fixture
    rows = MagicMock()
    rows.mappings.return_value.all.return_value = []
    session = MagicMock(execute=AsyncMock(return_value=rows))
    repository = IdeCheckpointOrphanRepository(MagicMock())
    assert await repository.retire_batch(storage_namespace=storage.namespace, session=session) == []
    sql = str(session.execute.await_args.args[0])
    for guard in (
        "NOT EXISTS (SELECT 1 FROM profile.ide_repository r",
        "upload_settled_at IS NOT NULL",
        "collected_at IS NULL",
        "active_checkpoint_id",
        "FOR UPDATE OF c SKIP LOCKED",
        "LIMIT :limit",
        "state='retired'",
        "published_at=NULL",
        "(c.repository_id,c.checkpoint_id)>(:after_repo,:after_checkpoint)",
    ):
        assert guard in sql
    assert "DELETE" not in sql and "clock_timestamp()-" not in sql
    await repository.acknowledge_discard(record.intent, session=session)
    sql, params = session.execute.await_args.args
    assert params == record.intent.params()
    for guard in (
        "thread_id=:thread_id",
        "user_id=:user_id",
        "allocation_id=:allocation_id",
        "sha256=:sha256",
        "size=:size",
        "storage_namespace=:storage_namespace",
        "base_checkpoint_id IS NOT DISTINCT FROM :base_checkpoint_id",
        "active_checkpoint_id",
        "upload_settled_at IS NOT NULL",
        "NOT EXISTS (SELECT 1 FROM profile.ide_repository r",
    ):
        assert guard in str(sql)


@pytest.mark.asyncio
async def test_original_writer_can_record_exact_settlement_after_deletion_without_publication(
    fixture,
):
    _, _, record, _ = fixture
    owner, ledger = MagicMock(), MagicMock()
    owner.first.return_value = None
    ledger.mappings.return_value.first.return_value = {
        **record.intent.params(),
        "state": "pending",
        "current_checkpoint_id": None,
        "upload_settled_at": object(),
    }
    session = MagicMock(execute=AsyncMock(side_effect=[owner, ledger]))
    outcome = await IdeCheckpointRepository(MagicMock()).mark_upload_settled(
        record.intent, session=session
    )
    assert outcome.upload_settled and outcome.state == "pending" and not outcome.is_current
    sql, params = session.execute.await_args.args
    assert params == record.intent.params()
    assert "NOT EXISTS (SELECT 1 FROM profile.ide_repository r" in str(sql)
    assert "collected_at=" not in str(sql) and "state=" not in str(sql)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [{"limit": True}, {"limit": 129}, {"after": (uuid4(),)}, {"after": [uuid4(), uuid4()]}],
)
async def test_invalid_orphan_scan_never_reaches_sql(kwargs):
    session = MagicMock(execute=AsyncMock())
    with pytest.raises(RepositoryError):
        await IdeCheckpointOrphanRepository(MagicMock()).retire_batch(
            storage_namespace="a" * 64, session=session, **kwargs
        )
    session.execute.assert_not_awaited()
