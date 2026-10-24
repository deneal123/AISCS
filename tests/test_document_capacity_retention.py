"""Compiler cleanup debt must retain admission capacity and its durable intent."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.build_store import BuildManifestStore
from application.documents.builds import DocumentBuildManager
from application.documents.projects import DocumentProjectError
from domain.documents import load_profile_catalog
from infrastructure.document_compiler import PreparedCompilerJob


@pytest.mark.asyncio
async def test_finished_job_with_retained_compiler_blocks_admission_before_prepare():
    compiler = SimpleNamespace(prepare=AsyncMock())
    manager = DocumentBuildManager(compiler, None, None, max_jobs=1)
    manager.recover = AsyncMock()
    manager._builds["cleanup-debt"] = SimpleNamespace(compiler_ref="a" * 64)
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await manager.start(None, None, project_path="report", expected_revision="rev", final=False)
    compiler.prepare.assert_not_awaited()


@pytest.mark.parametrize("now", [100, 100_000])
def test_pruning_does_not_erase_cleanup_intent_or_final_delivery_sources(now):
    builds = tuple(
        SimpleNamespace(
            build_id=str(index),
            operation_id="",
            state="failed",
            compiler_ref="a" * 64 if index == 0 else "",
            final=index == 1,
            completed_at=float(index + 1),
            created_at=float(index + 1),
        )
        for index in range(70)
    )
    candidates = BuildManifestStore.prune_candidates(builds, now=now)
    assert "0" not in candidates and "1" not in candidates
    assert "2" in candidates


@pytest.mark.asyncio
async def test_concurrent_preparation_cannot_bypass_admission_and_cancel_releases_reservation():
    manager = DocumentBuildManager(None, None, None, max_jobs=1)
    manager.recover = AsyncMock()
    manager._reserve_manifest = AsyncMock()
    item = SimpleNamespace(workspace_id="owned")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def preparing(*_args, **_kwargs):
        entered.set()
        await release.wait()

    manager._start_reserved = AsyncMock(side_effect=preparing)
    first = asyncio.create_task(
        manager.start(None, item, project_path="one", expected_revision="rev", final=False)
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
            await manager.start(
                None, item, project_path="two", expected_revision="rev", final=False
            )
        assert manager._start_reserved.await_count == 1
    finally:
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
    assert manager._admission.preparing == 0
    result = object()
    manager._start_reserved = AsyncMock(return_value=result)
    assert (
        await manager.start(None, item, project_path="three", expected_revision="rev", final=False)
        is result
    )
    assert manager._admission.preparing == 0


@pytest.mark.asyncio
async def test_failed_preparation_releases_only_its_reservation():
    manager = DocumentBuildManager(None, None, None, max_jobs=1)
    manager.recover = AsyncMock()
    manager._reserve_manifest = AsyncMock()
    manager._start_reserved = AsyncMock(side_effect=DocumentProjectError("revision_conflict"))
    with pytest.raises(DocumentProjectError, match="revision_conflict"):
        await manager.start(
            None,
            SimpleNamespace(workspace_id="owned"),
            project_path="one",
            expected_revision="stale",
            final=False,
        )
    assert manager._admission.preparing == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_succeeds", [False, True])
@pytest.mark.parametrize("failure", ["manifest", "cancel", "persistent_manifest"])
async def test_manifest_failure_after_prepare_leaves_retryable_cleanup(cleanup_succeeds, failure):
    @asynccontextmanager
    async def operation(_item):
        yield

    registry = SimpleNamespace(operation=operation)
    item = SimpleNamespace(
        workspace_id="owned", ref=object(), policy=SimpleNamespace(root="/workspace")
    )

    async def prepare(*_args, **kwargs):
        job = PreparedCompilerJob("build-owned", "a" * 64, "paper")
        await kwargs["before_create"](job.job_ref)
        await kwargs["on_allocated"](job)
        return job

    compiler = SimpleNamespace(
        prepare=AsyncMock(side_effect=prepare),
        cleanup_recovered=AsyncMock(return_value=cleanup_succeeds),
        execute=AsyncMock(),
    )
    projects = SimpleNamespace(
        manifest=AsyncMock(return_value=({}, load_profile_catalog().get("generic_article"))),
        digest=AsyncMock(return_value="d" * 64),
    )
    manager = DocumentBuildManager(compiler, projects, AsyncMock(return_value="rev"), max_jobs=1)
    manager.store.save = AsyncMock()
    manager.recover = AsyncMock()
    error = (
        asyncio.CancelledError()
        if failure == "cancel"
        else DocumentProjectError("runtime_unavailable")
    )
    manager._persist = AsyncMock(
        side_effect=error if failure == "persistent_manifest" else [error, None, None]
    )
    with pytest.raises(type(error)):
        await manager.start(
            registry, item, project_path="paper", expected_revision="rev", final=False
        )
    build = manager._builds["build-owned"]
    assert build.state == ("cancelled" if failure == "cancel" else "failed")
    assert build.failure_code == ("cancelled" if failure == "cancel" else "runtime_unavailable")
    assert build.completed_at > 0
    reference_cleared = cleanup_succeeds and failure != "persistent_manifest"
    assert build.compiler_ref == ("" if reference_cleared else "a" * 64)
    assert manager._occupied_compiler_slots() == int(not reference_cleared)
    assert manager._admission.preparing == 0
    assert not manager._tasks
    compiler.execute.assert_not_awaited()
    compiler.cleanup_recovered.assert_awaited_once_with("a" * 64, item.ref, build.build_id)
    if not reference_cleared:
        compiler.cleanup_recovered.return_value = True
        manager._persist = AsyncMock()
        await manager._cleanup_interrupted_compiler(registry, item, build)
        assert not build.compiler_ref and manager._occupied_compiler_slots() == 0


@asynccontextmanager
async def _operation(_item):
    yield


def _retained(index, *, final=True, state="ready", workspace="owned"):
    return SimpleNamespace(
        build_id=str(index),
        operation_id="",
        workspace_id=workspace,
        state=state,
        final=final,
        compiler_ref="",
        created_at=1e12 + index,
        completed_at=1e12 + index,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("protected_count", [64, 65])
async def test_full_protected_registry_refuses_before_new_container_without_deletion(
    protected_count,
):
    compiler = SimpleNamespace(prepare=AsyncMock())
    store = BuildManifestStore()
    store.delete = AsyncMock()
    manager = DocumentBuildManager(compiler, None, None, store=store)
    manager.recover = AsyncMock()
    manager._builds = {str(i): _retained(i) for i in range(protected_count)}
    registry = SimpleNamespace(operation=_operation)
    item = SimpleNamespace(workspace_id="owned")
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await manager.start(
            registry, item, project_path="paper", expected_revision="rev", final=True
        )
    compiler.prepare.assert_not_awaited()
    store.delete.assert_not_awaited()
    assert len(manager._builds) == protected_count
    assert manager._admission.preparing == 0


@pytest.mark.asyncio
async def test_manifest_cap_is_workspace_local_and_preserves_other_workspace_records():
    manager = DocumentBuildManager(None, None, None)
    manager.recover = AsyncMock()
    manager._builds = {str(i): _retained(i, workspace="other") for i in range(64)}
    result = object()
    manager._start_reserved = AsyncMock(return_value=result)
    assert (
        await manager.start(
            SimpleNamespace(operation=_operation),
            SimpleNamespace(workspace_id="owned"),
            project_path="paper",
            expected_revision="rev",
            final=True,
        )
        is result
    )
    assert len(manager._builds) == 64


@pytest.mark.asyncio
async def test_manifest_reservation_reclaims_preview_and_counts_active_records():
    store = BuildManifestStore()
    store.delete = AsyncMock()
    manager = DocumentBuildManager(None, None, None, store=store)
    manager._builds = {str(i): _retained(i) for i in range(62)}
    manager._builds["62"] = _retained(62, final=False)
    manager._builds["63"] = _retained(63, state="building")
    await manager._reserve_manifest(
        SimpleNamespace(operation=_operation), SimpleNamespace(workspace_id="owned")
    )
    store.delete.assert_awaited_once()
    assert "62" not in manager._builds
    assert "63" in manager._builds and len(manager._builds) == 63


@pytest.mark.asyncio
async def test_same_workspace_concurrent_final_starts_cannot_overbook_last_manifest():
    manager = DocumentBuildManager(None, None, None)
    manager.recover = AsyncMock()
    manager._builds = {str(i): _retained(i) for i in range(63)}
    entered, release = asyncio.Event(), asyncio.Event()

    async def prepare(*_args, **_kwargs):
        entered.set()
        await release.wait()
        result = _retained(63, state="building")
        manager._builds[result.build_id] = result
        return result

    manager._start_reserved = AsyncMock(side_effect=prepare)
    registry = SimpleNamespace(operation=_operation)
    item = SimpleNamespace(workspace_id="owned")
    kwargs = dict(project_path="paper", expected_revision="rev", final=True)
    first = asyncio.create_task(manager.start(registry, item, **kwargs))
    second = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        second = asyncio.create_task(manager.start(registry, item, **kwargs))
        await asyncio.sleep(0)
        assert manager._start_reserved.await_count == 1
        release.set()
        assert (await asyncio.wait_for(first, 1)).build_id == "63"
        with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
            await asyncio.wait_for(second, 1)
        assert len(manager._builds) == 64 and manager._admission.preparing == 0
    finally:
        release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (first, second) if task is not None), return_exceptions=True
        )


@pytest.mark.asyncio
async def test_failed_manifest_delete_does_not_release_registry_slot():
    store = BuildManifestStore()
    manager = DocumentBuildManager(None, None, None, store=store)
    manager._builds = {str(i): _retained(i) for i in range(63)}
    manager._builds["63"] = _retained(63, final=False)
    registry = SimpleNamespace(
        operation=_operation,
        exec_raw=AsyncMock(return_value=SimpleNamespace(stdout="", exit_code=1)),
    )
    item = SimpleNamespace(workspace_id="owned", policy=SimpleNamespace(root="/workspace"))
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await manager._reserve_manifest(registry, item)
    assert len(manager._builds) == 64 and "63" in manager._builds


@pytest.mark.asyncio
async def test_pruning_does_not_forget_task_during_final_manifest_cleanup():
    store = BuildManifestStore()
    store.delete = AsyncMock()
    manager = DocumentBuildManager(None, None, None, store=store)
    manager._builds = {str(i): _retained(i) for i in range(63)}
    manager._builds["63"] = _retained(63, final=False)
    task = asyncio.create_task(asyncio.Event().wait())
    manager._tasks["63"] = task
    try:
        with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
            await manager._reserve_manifest(
                SimpleNamespace(operation=_operation), SimpleNamespace(workspace_id="owned")
            )
        store.delete.assert_not_awaited()
        assert manager._tasks["63"] is task and "63" in manager._builds
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
