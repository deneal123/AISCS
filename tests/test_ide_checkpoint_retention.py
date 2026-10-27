"""Bounded post-publication retention; no deletion on uncertain SQL decisions."""

import hashlib
import io
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.services.chat.application.ide.checkpoints.retention import (
    IdeCheckpointRetentionService,
)
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.revision import CheckpointIntent, CheckpointRecord
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.checkpoints.retention import (
    RETAINED_CHECKPOINTS,
    IdeCheckpointRetentionRepository,
)
from service.shared.repositories.exceptions import RepositoryError, RepositoryOperationalError


@pytest.fixture
def fixture(tmp_path):
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    storage = IdeCheckpointStorage(LocalFileStorage(tmp_path), max_bytes=1000)
    body = b"retention fixture"
    blob = CheckpointBlob(scope, uuid4(), hashlib.sha256(body).hexdigest(), len(body))
    intent = CheckpointIntent(blob, uuid4(), None, storage.namespace)
    record = CheckpointRecord(intent, "retired", uuid4(), upload_settled=True)
    repository = MagicMock(
        retire_history=AsyncMock(return_value=[record]),
        acknowledge_discard=AsyncMock(return_value=True),
    )
    return scope, storage, body, record, repository


@pytest.mark.asyncio
async def test_committed_tombstone_deletes_only_exact_owned_object_idempotently(fixture):
    scope, storage, body, record, repository = fixture
    await storage.put(scope, record.intent.blob, io.BytesIO(body))
    service = IdeCheckpointRetentionService(repository, storage)
    for _ in range(2):
        result = await service.run(scope, uuid4())
        assert result.acknowledged == 1 and not result.pending
    repository.acknowledge_discard.assert_awaited_with(record.intent)
    with pytest.raises(IdeCheckpointError):
        async with storage.open(scope, record.intent.blob):
            pytest.fail("retired object still exists")


@pytest.mark.asyncio
async def test_lost_retirement_commit_ack_cannot_delete_any_object(fixture):
    scope, storage, _, _, repository = fixture
    repository.retire_history.side_effect = RepositoryOperationalError("private db")
    storage.discard = AsyncMock()
    assert (await IdeCheckpointRetentionService(repository, storage).run(scope, uuid4())).pending
    storage.discard.assert_not_awaited()
    repository.acknowledge_discard.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("has_head", [False, True])
async def test_sweep_reconciles_committed_work_with_or_without_a_published_head(fixture, has_head):
    scope, storage, body, record, repository = fixture
    await storage.put(scope, record.intent.blob, io.BytesIO(body))
    head = uuid4() if has_head else None
    cursor = uuid4()
    repository.maintenance_scopes = AsyncMock(return_value=[(scope, head)])
    repository.pending_cleanup = AsyncMock(return_value=[record])
    result = await IdeCheckpointRetentionService(repository, storage).sweep(
        after_repository_id=cursor
    )
    assert result.repositories == 1 and result.delete_acknowledged == 1 and result.pending == 0
    assert result.cursor == scope.repository_id
    repository.maintenance_scopes.assert_awaited_once_with(
        storage_namespace=storage.namespace, limit=32, after_repository_id=cursor
    )
    repository.acknowledge_discard.assert_awaited_once_with(record.intent)
    if has_head:
        repository.pending_cleanup.assert_not_awaited()
    else:
        repository.retire_history.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_repository_does_not_starve_the_next_sweep_page(fixture):
    scope, storage, _, _, repository = fixture
    repository.maintenance_scopes = AsyncMock(return_value=[(scope, uuid4())])
    repository.retire_history.side_effect = RepositoryOperationalError("private db")
    storage.discard = AsyncMock()
    result = await IdeCheckpointRetentionService(repository, storage).sweep()
    assert result.pending == 1 and result.cursor == scope.repository_id
    storage.discard.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_sweep_wraps_without_changing_any_checkpoint(fixture):
    _, storage, _, _, repository = fixture
    repository.maintenance_scopes = AsyncMock(return_value=[])
    result = await IdeCheckpointRetentionService(repository, storage).sweep()
    assert result.repositories == 0 and result.cursor is None
    repository.acknowledge_discard.assert_not_awaited()


@pytest.mark.asyncio
async def test_maintenance_discovery_is_bounded_owned_and_excludes_unsettled_writers(fixture):
    scope, storage, _, _, _ = fixture
    rows = MagicMock()
    rows.mappings.return_value.all.return_value = [{**scope.params(), "checkpoint_id": None}]
    session = MagicMock(execute=AsyncMock(return_value=rows))
    result = await IdeCheckpointRetentionRepository(MagicMock()).maintenance_scopes(
        storage_namespace=storage.namespace, session=session
    )
    assert result == [(scope, None)]
    sql = str(session.execute.await_args.args[0])
    for required in (
        "t.user_id=r.user_id",
        "c.user_id=r.user_id",
        "c.thread_id=r.thread_id",
        "upload_settled_at IS NOT NULL",
        "collected_at IS NULL",
        "active_checkpoint_id",
        "IS DISTINCT FROM h.checkpoint_id",
        "storage_namespace=:storage_namespace",
        "LIMIT :limit",
        "r.repository_id>:after_repository_id",
    ):
        assert required in sql
    assert "UPDATE" not in sql and "DELETE" not in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, 129, True])
async def test_invalid_sweep_batch_never_touches_database(limit):
    session = MagicMock(execute=AsyncMock())
    with pytest.raises(RepositoryError):
        await IdeCheckpointRetentionRepository(MagicMock()).maintenance_scopes(
            storage_namespace="a" * 64, limit=limit, session=session
        )
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "published", "retired_head"])
async def test_nonretired_or_current_records_never_reach_object_storage(fixture, state):
    scope, storage, _, record, repository = fixture
    repository.retire_history.return_value = [
        replace(
            record,
            state="retired" if state == "retired_head" else state,
            current_checkpoint_id=record.intent.blob.checkpoint_id
            if state == "retired_head"
            else None,
        )
    ]
    storage.discard = AsyncMock()
    with pytest.raises(IdeCheckpointError, match="ide_checkpoint_cleanup_unavailable"):
        await IdeCheckpointRetentionService(repository, storage).run(scope, uuid4())
    storage.discard.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["delete", "namespace", "ack", "ack_missing"])
async def test_cleanup_failure_keeps_retryable_ledger_without_republishing(fixture, failure):
    scope, storage, _, record, repository = fixture
    storage.discard = AsyncMock()
    if failure == "delete":
        storage.discard.side_effect = IdeCheckpointError("ide_checkpoint_cleanup_unavailable")
    elif failure == "namespace":
        repository.retire_history.return_value = [
            replace(record, intent=replace(record.intent, storage_namespace="a" * 64))
        ]
    elif failure == "ack":
        repository.acknowledge_discard.side_effect = RepositoryOperationalError("private db")
    else:
        repository.acknowledge_discard.return_value = False
    result = await IdeCheckpointRetentionService(repository, storage).run(scope, uuid4())
    assert result.pending
    if failure not in {"ack", "ack_missing"}:
        repository.acknowledge_discard.assert_not_awaited()
    if failure == "namespace":
        storage.discard.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_scope_does_not_delete_object(fixture):
    scope, storage, _, record, _ = fixture
    storage.storage.delete_file = AsyncMock()
    with pytest.raises(IdeCheckpointError, match="ide_checkpoint_scope_forbidden"):
        await storage.discard(replace(scope, user_id=uuid4()), record.intent.blob)
    storage.storage.delete_file.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unsettled", "collected"])
async def test_cleanup_cannot_release_accounting_for_an_unknown_writer(fixture, change):
    scope, storage, _, record, repository = fixture
    repository.retire_history.return_value = [
        replace(record, upload_settled=change != "unsettled", collected=change == "collected")
    ]
    storage.discard = AsyncMock()
    result = await IdeCheckpointRetentionService(repository, storage).run(scope, uuid4())
    assert result.pending is (change == "unsettled")
    storage.discard.assert_not_awaited()
    repository.acknowledge_discard.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("owned,confirmed", [(False, None), (True, None), (True, 1)])
async def test_sql_retirement_requires_owner_and_current_publication(fixture, owned, confirmed):
    scope, storage, _, _, _ = fixture
    owner = MagicMock()
    owner.first.return_value = (scope.repository_id,) if owned else None
    rows = MagicMock()
    rows.mappings.return_value.all.return_value = []
    session = MagicMock(
        execute=AsyncMock(side_effect=[owner, MagicMock(), rows]),
        scalar=AsyncMock(return_value=confirmed),
    )
    result = await IdeCheckpointRetentionRepository(MagicMock()).retire_history(
        scope, after_checkpoint_id=uuid4(), storage_namespace=storage.namespace, session=session
    )
    assert result == []
    queries = [str(call.args[0]) for call in session.execute.await_args_list]
    assert "FOR UPDATE OF r FOR SHARE OF t" in queries[0]
    if not owned or confirmed is None:
        assert len(queries) == 1
    else:
        assert RETAINED_CHECKPOINTS == 11
        assert "LIMIT :keep" in queries[1] and "active_checkpoint_id" in queries[1]
        assert "head.checkpoint_id=c.checkpoint_id" in queries[1]
        assert "LIMIT 32" in queries[2] and "active_checkpoint_id" in queries[2]
        assert "DELETE FROM" not in " ".join(queries)
