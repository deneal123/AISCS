"""Recovery never cleans unowned paths or re-snapshots changed user content."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.projects import DocumentProjectError
from application.documents.source_recovery import SourcePublicationRecovery


def _record(**changes):
    value = {
        "schema_version": 1,
        "token": "a" * 16,
        "project_path": "documents/test",
        "old_digest": "b" * 64,
        "new_digest": "c" * 64,
        **changes,
    }
    return {"filename": "a" * 16 + ".json", "value": value}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"token": "../escape"},
        {"project_path": "../escape"},
        {"project_path": "."},
        {"project_path": ".gpthub-document/private"},
        {"new_digest": "unknown"},
    ],
)
async def test_invalid_journal_never_reaches_cleanup_or_snapshot(changes):
    run = AsyncMock(return_value=SimpleNamespace(stdout=json.dumps([_record(**changes)])))
    snapshot = AsyncMock()
    with pytest.raises(DocumentProjectError, match="authoring_publish_failed"):
        await SourcePublicationRecovery(run, snapshot).recover(
            SimpleNamespace(policy=SimpleNamespace(root="/workspace"))
        )
    assert run.await_count == 1
    snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_changed_project_retains_journal_and_backups():
    run = AsyncMock(
        side_effect=[
            SimpleNamespace(stdout=json.dumps([_record()])),
            SimpleNamespace(stdout="d" * 64),
        ]
    )
    snapshot = AsyncMock()
    recovery = SourcePublicationRecovery(run, snapshot)
    counts = await recovery.recover(SimpleNamespace(policy=SimpleNamespace(root="/workspace")))
    assert counts == {"recovered": 0, "pending": 1, "conflicted": 1}
    assert recovery.health() == counts
    assert run.await_count == 2
    snapshot.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["", "null", "{}", "private-marker"])
async def test_malformed_inventory_is_bounded_and_fail_closed(body):
    run = AsyncMock(return_value=SimpleNamespace(stdout=body))
    snapshot = AsyncMock()
    with pytest.raises(DocumentProjectError, match="authoring_publish_failed") as error:
        await SourcePublicationRecovery(run, snapshot).recover(
            SimpleNamespace(policy=SimpleNamespace(root="/workspace"))
        )
    assert "private-marker" not in str(error.value)
    snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_snapshot_preserves_recovery_record_for_retry():
    run = AsyncMock(
        side_effect=[
            SimpleNamespace(stdout=json.dumps([_record()])),
            SimpleNamespace(stdout="c" * 64),
        ]
    )
    snapshot = AsyncMock(return_value={"committed": False, "reason": "failed"})
    with pytest.raises(DocumentProjectError, match="authoring_publish_failed"):
        await SourcePublicationRecovery(run, snapshot).recover(
            SimpleNamespace(policy=SimpleNamespace(root="/workspace"))
        )
    assert run.await_count == 2


@pytest.mark.asyncio
async def test_registry_reconciliation_uses_the_workspace_operation_guard():
    item = SimpleNamespace(policy=SimpleNamespace(root="/workspace"))
    held = False

    @asynccontextmanager
    async def operation(owned):
        nonlocal held
        assert owned is item
        held = True
        try:
            yield
        finally:
            held = False

    async def run(*arguments):
        assert held
        return SimpleNamespace(stdout="[]")

    recovery = SourcePublicationRecovery(run, AsyncMock())
    registry = SimpleNamespace(
        active_workspaces=AsyncMock(return_value=[item]), operation=operation
    )
    await recovery.reconcile_registry(registry)
    assert not held
    assert recovery.health() == {"recovered": 0, "pending": 0, "conflicted": 0}
