"""Startup recovery must not turn unknown compiler debt into free capacity."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.build_store import BuildManifestStore
from application.documents.builds import DocumentBuildManager
from application.documents.projects import DocumentProjectError
from domain.documents import DocumentBuild


@asynccontextmanager
async def operation(_item):
    yield


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(stdout="", exit_code=1),
        SimpleNamespace(stdout="", exit_code=0, truncated=True),
        SimpleNamespace(stdout="", exit_code=0, timed_out=True),
        SimpleNamespace(stdout="{}\n" * 257, exit_code=0),
    ],
)
async def test_incomplete_manifest_inventory_is_not_successful_empty_recovery(result):
    registry = SimpleNamespace(exec_raw=AsyncMock(return_value=result))
    item = SimpleNamespace(workspace_id="owned", policy=SimpleNamespace(root="/workspace"))
    with pytest.raises(RuntimeError):
        await BuildManifestStore().load(registry, item)


@pytest.mark.asyncio
@pytest.mark.parametrize("flags", [{"exit_code": 1}, {"truncated": True}, {"timed_out": True}])
async def test_manifest_save_marker_does_not_override_failed_transport(flags):
    result = SimpleNamespace(stdout="__OK__", exit_code=0)
    for key, value in flags.items():
        setattr(result, key, value)
    registry = SimpleNamespace(exec_raw=AsyncMock(return_value=result))
    item = SimpleNamespace(workspace_id="owned", policy=SimpleNamespace(root="/workspace"))
    build = DocumentBuild(
        "job",
        "owned",
        "/workspace/paper",
        "generic_document",
        1,
        "revision",
        "d" * 64,
        "draft",
        False,
    )
    with pytest.raises(RuntimeError, match="manifest unavailable"):
        await BuildManifestStore().save(registry, item, build)


@pytest.mark.asyncio
@pytest.mark.parametrize("flags", [{"exit_code": 1}, {"truncated": True}, {"timed_out": True}])
async def test_uncertain_manifest_deletion_preserves_prunable_record_until_retry(flags):
    result = SimpleNamespace(stdout="__OK__", exit_code=0)
    for key, value in flags.items():
        setattr(result, key, value)
    registry = SimpleNamespace(exec_raw=AsyncMock(return_value=result), operation=operation)
    item = SimpleNamespace(workspace_id="owned", policy=SimpleNamespace(root="/workspace"))
    build = DocumentBuild(
        "expired-preview",
        "owned",
        "/workspace/paper",
        "generic_document",
        1,
        "revision",
        "d" * 64,
        "draft",
        False,
    )
    build.state = "failed"
    build.created_at = 1
    build.completed_at = 2
    manager = DocumentBuildManager(None, None, None)
    manager._builds[build.build_id] = build

    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await manager._prune(registry, item)
    assert manager._builds[build.build_id] is build
    assert manager.manifest_failures == 1

    registry.exec_raw.return_value = SimpleNamespace(stdout="__OK__", exit_code=0)
    await manager._prune(registry, item)
    assert build.build_id not in manager._builds
    assert registry.exec_raw.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["{", "{}", "null", "[]", '{"schema_version":99}'])
async def test_corrupt_individual_manifest_is_not_silently_omitted(body):
    registry = SimpleNamespace(
        exec_raw=AsyncMock(return_value=SimpleNamespace(stdout=body, exit_code=0))
    )
    item = SimpleNamespace(workspace_id="owned", policy=SimpleNamespace(root="/workspace"))
    with pytest.raises(RuntimeError, match="manifest inventory invalid"):
        await BuildManifestStore().load(registry, item)


@pytest.mark.asyncio
async def test_mixed_valid_and_foreign_record_does_not_publish_partial_inventory():
    import json

    valid = DocumentBuild(
        "build-owned",
        "owned",
        "/workspace/paper",
        "generic_document",
        1,
        "revision",
        "d" * 64,
        "draft",
        False,
    ).manifest_dict()
    foreign = dict(valid, workspace_id="foreign", build_id="build-foreign")
    registry = SimpleNamespace(
        exec_raw=AsyncMock(
            return_value=SimpleNamespace(
                stdout=json.dumps(valid) + "\n" + json.dumps(foreign), exit_code=0
            )
        )
    )
    item = SimpleNamespace(workspace_id="owned", policy=SimpleNamespace(root="/workspace"))
    with pytest.raises(RuntimeError, match="manifest inventory invalid"):
        await BuildManifestStore().load(registry, item)


@pytest.mark.asyncio
@pytest.mark.parametrize("same_payload", [True, False])
async def test_duplicate_build_identity_blocks_recovery_before_cleanup(same_payload):
    import json

    first = DocumentBuild(
        "duplicate-build",
        "owned",
        "/workspace/paper",
        "generic_document",
        1,
        "revision",
        "d" * 64,
        "draft",
        False,
    ).manifest_dict()
    first["state"] = "failed"
    second = dict(first) if same_payload else dict(first, source_digest="e" * 64)
    registry = SimpleNamespace(
        exec_raw=AsyncMock(
            return_value=SimpleNamespace(
                stdout=json.dumps(first) + "\n" + json.dumps(second), exit_code=0
            )
        ),
        operation=operation,
    )
    item = SimpleNamespace(workspace_id="owned", policy=SimpleNamespace(root="/workspace"))
    manager = DocumentBuildManager(None, None, None)
    manager._cleanup_interrupted_compiler = AsyncMock()
    manager._prune = AsyncMock()
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await manager.recover(registry, item)
    assert not manager._builds
    assert "owned" in manager._pending_recovery
    assert "owned" not in manager._recovered_workspaces
    manager._cleanup_interrupted_compiler.assert_not_awaited()
    manager._prune.assert_not_awaited()

    registry.exec_raw.return_value = SimpleNamespace(stdout=json.dumps(first), exit_code=0)
    await manager.recover(registry, item)
    assert set(manager._builds) == {"duplicate-build"}
    assert "owned" not in manager._pending_recovery


@pytest.mark.asyncio
async def test_cross_workspace_build_identity_collision_preserves_first_owner():
    store = BuildManifestStore()
    good, bad = (SimpleNamespace(workspace_id=value) for value in ("good", "bad"))
    first = DocumentBuild(
        "same-id",
        "good",
        "/workspace/paper",
        "generic_document",
        1,
        "rev",
        "d" * 64,
        "draft",
        False,
    )
    second = DocumentBuild(
        "same-id",
        "bad",
        "/workspace/paper",
        "generic_document",
        1,
        "rev",
        "e" * 64,
        "draft",
        False,
    )
    first.state = second.state = "failed"
    store.load = AsyncMock(side_effect=[(first,), (second,)])
    manager = DocumentBuildManager(None, None, None, store=store)
    manager._cleanup_interrupted_compiler = AsyncMock()
    manager._prune = AsyncMock()
    registry = SimpleNamespace(operation=operation)
    await manager.recover(registry, good)
    manager._cleanup_interrupted_compiler.reset_mock()
    manager._prune.reset_mock()
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await manager.recover(registry, bad)
    assert manager._builds["same-id"] is first
    assert "bad" in manager._pending_recovery
    assert "bad" not in manager._recovered_workspaces
    manager._cleanup_interrupted_compiler.assert_not_awaited()
    manager._prune.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_workspace_recovery_cannot_claim_the_same_build_id():
    entered, release = asyncio.Event(), asyncio.Event()
    good, bad = (SimpleNamespace(workspace_id=value) for value in ("good", "bad"))

    async def load(_registry, item):
        if item.workspace_id == "good":
            entered.set()
            await release.wait()
        build = DocumentBuild(
            "shared-id",
            item.workspace_id,
            "/workspace/paper",
            "generic_document",
            1,
            "rev",
            "d" * 64,
            "draft",
            False,
        )
        build.state = "failed"
        return (build,)

    store = BuildManifestStore()
    store.load = AsyncMock(side_effect=load)
    manager = DocumentBuildManager(None, None, None, store=store)
    manager._cleanup_interrupted_compiler = AsyncMock()
    manager._prune = AsyncMock()
    registry = SimpleNamespace(operation=operation)
    first = asyncio.create_task(manager.recover(registry, good))
    second = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        second = asyncio.create_task(manager.recover(registry, bad))
        await asyncio.sleep(0)
        assert store.load.await_count == 1
        release.set()
        await asyncio.wait_for(first, 1)
        with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
            await asyncio.wait_for(second, 1)
        assert manager._builds["shared-id"].workspace_id == "good"
        assert manager._pending_recovery == {"bad"}
        manager._cleanup_interrupted_compiler.assert_awaited_once()
        manager._prune.assert_awaited_once()
    finally:
        release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (first, second) if task is not None), return_exceptions=True
        )


@pytest.mark.asyncio
async def test_other_workspace_recovery_failure_blocks_new_compiler_until_reconciled():
    good, bad = (SimpleNamespace(workspace_id=value) for value in ("good", "bad"))
    outage = True

    async def load(_registry, item):
        if item.workspace_id == "bad" and outage:
            raise RuntimeError("private failure marker")
        return ()

    store = BuildManifestStore()
    store.load = AsyncMock(side_effect=load)
    compiler = SimpleNamespace(reconcile=AsyncMock(return_value=0), prepare=AsyncMock())
    registry = SimpleNamespace(
        operation=operation, active_workspaces=AsyncMock(return_value=(bad, good))
    )
    manager = DocumentBuildManager(compiler, None, None, store=store)
    result = object()
    manager._start_reserved = AsyncMock(return_value=result)
    await manager.reconcile_registry(registry)
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await manager.start(
            registry, good, project_path="paper", expected_revision="rev", final=False
        )
    manager._start_reserved.assert_not_awaited()
    compiler.prepare.assert_not_awaited()
    outage = False
    await manager.reconcile_registry(registry)
    assert (
        await manager.start(
            registry, good, project_path="paper", expected_revision="rev", final=False
        )
        is result
    )


@pytest.mark.asyncio
async def test_concurrent_recovery_waits_for_complete_inventory_instead_of_returning_early():
    entered, release = asyncio.Event(), asyncio.Event()

    async def load(*_args):
        entered.set()
        await release.wait()
        return ()

    store = BuildManifestStore()
    store.load = AsyncMock(side_effect=load)
    manager = DocumentBuildManager(None, None, None, store=store)
    registry = SimpleNamespace(operation=operation)
    item = SimpleNamespace(workspace_id="owned")
    first = asyncio.create_task(manager.recover(registry, item))
    second = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        second = asyncio.create_task(manager.recover(registry, item))
        await asyncio.sleep(0)
        assert not second.done()
        assert "owned" not in manager._recovered_workspaces
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 1)
        store.load.assert_awaited_once()
        assert "owned" in manager._recovered_workspaces
    finally:
        release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (first, second) if task is not None), return_exceptions=True
        )
