"""Preparation failures keep compiler cleanup ownership before manager handoff."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.builds import DocumentBuildManager
from infrastructure import document_compiler
from infrastructure.document_compiler import CompilerFailure, DockerDocumentCompiler


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [asyncio.CancelledError, RuntimeError])
@pytest.mark.parametrize("removed", [True, False])
async def test_preparation_failure_cleans_or_retains_capacity_before_handoff(
    monkeypatch, failure, removed
):
    compiler = DockerDocumentCompiler()
    compiler._validate_source = AsyncMock()
    compiler.destroy = AsyncMock(return_value=removed)
    command = AsyncMock(side_effect=[(0, b"a" * 64), (0, b""), (0, b"")])
    monkeypatch.setattr(document_compiler, "_command", command)
    monkeypatch.setattr(document_compiler, "_pipe", AsyncMock(side_effect=failure()))
    with pytest.raises(failure):
        await compiler.prepare(
            SimpleNamespace(container_id="owned-source"),
            workspace_root="/workspace",
            project_path="/workspace/paper",
        )
    compiler.destroy.assert_awaited_once_with("a" * 64)
    assert compiler.pending_preparation_cleanup == int(not removed)
    manager = DocumentBuildManager(compiler, None, None)
    assert manager._occupied_compiler_slots() == int(not removed)
    if not removed:
        compiler.cleanup_recovered = AsyncMock(return_value=True)
        monkeypatch.setattr(document_compiler, "_command", AsyncMock(return_value=(0, b"")))
        await compiler.reconcile()
        compiler.cleanup_recovered.assert_awaited_once()
        assert compiler.pending_preparation_cleanup == 0
        assert manager._occupied_compiler_slots() == 0


@pytest.mark.asyncio
async def test_create_cancellation_waits_for_owned_creation_before_cleanup(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    compiler = DockerDocumentCompiler()
    compiler._validate_source = AsyncMock()
    compiler.destroy = AsyncMock(return_value=True)

    async def create(*_args, **_kwargs):
        entered.set()
        await release.wait()
        return 0, b"a" * 64

    monkeypatch.setattr(document_compiler, "_command", create)
    task = asyncio.create_task(
        compiler.prepare(
            SimpleNamespace(container_id="owned"),
            workspace_root="/workspace",
            project_path="/workspace/paper",
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        compiler.destroy.assert_awaited_once_with("a" * 64)
        assert compiler.pending_preparation_cleanup == 0
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_cancellation_retains_inflight_creation_until_owned_cleanup(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    compiler = DockerDocumentCompiler()
    compiler._validate_source = AsyncMock()
    allocated = AsyncMock()

    async def create(*_args, **_kwargs):
        entered.set()
        await release.wait()
        return 0, b"a" * 64

    monkeypatch.setattr(document_compiler, "_command", create)
    task = asyncio.create_task(
        compiler.prepare(
            SimpleNamespace(container_id="owned"),
            workspace_root="/workspace",
            project_path="/workspace/paper",
            on_allocated=allocated,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert compiler.pending_preparation_cleanup == 1
        manager = DocumentBuildManager(compiler, None, None)
        assert manager._occupied_compiler_slots() == 1
        assert len(compiler._creating) == 1
        release.set()
        await asyncio.wait_for(asyncio.gather(*compiler._creating.values()), 1)
        # The abandoned create task must never write a manifest after its
        # caller has released the workspace operation guard.
        allocated.assert_not_awaited()
        compiler.cleanup_recovered = AsyncMock(return_value=True)
        monkeypatch.setattr(
            document_compiler, "_command", AsyncMock(side_effect=[(0, b"a" * 64), (0, b"")])
        )
        await compiler.reconcile()
        compiler.cleanup_recovered.assert_awaited_once()
        assert compiler.pending_preparation_cleanup == 0 and not compiler._creating
        assert manager._occupied_compiler_slots() == 0
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, *compiler._creating.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_unknown_create_timeout_retains_capacity_across_empty_inventory_until_late_commit(
    monkeypatch,
):
    compiler = DockerDocumentCompiler()
    compiler._validate_source = AsyncMock()
    monkeypatch.setattr(
        document_compiler, "_command", AsyncMock(side_effect=CompilerFailure("runtime_unavailable"))
    )
    workspace_ref = SimpleNamespace(container_id="owned")
    with pytest.raises(CompilerFailure):
        await compiler.prepare(
            workspace_ref, workspace_root="/workspace", project_path="/workspace/paper"
        )
    assert compiler.pending_preparation_cleanup == 1
    manager = DocumentBuildManager(compiler, None, None)
    monkeypatch.setattr(document_compiler, "_command", AsyncMock(return_value=(0, b"")))
    await compiler.reconcile()
    assert compiler.pending_preparation_cleanup == 1
    assert manager._occupied_compiler_slots() == 1
    compiler.cleanup_recovered = AsyncMock(return_value=True)
    monkeypatch.setattr(
        document_compiler, "_command", AsyncMock(side_effect=[(0, b"a" * 64), (0, b"")])
    )
    await compiler.reconcile()
    compiler.cleanup_recovered.assert_awaited_once()
    assert compiler.pending_preparation_cleanup == 0
    assert manager._occupied_compiler_slots() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [True, False])
async def test_preparation_name_becomes_exact_id_only_after_ownership_witness(monkeypatch, owned):
    compiler = DockerDocumentCompiler()
    job = "e" * 24
    ref = SimpleNamespace(container_id="owned")
    compiler._preparation_cleanup[job] = (ref, "gpthub-doc-" + job)
    record = {
        "Name": "/gpthub-doc-" + job,
        "Config": {
            "Labels": {
                "gpthub.document": "1",
                "gpthub.document.contract": "1",
                "gpthub.document.workspace_container": "owned" if owned else "foreign",
            }
        },
    }
    monkeypatch.setattr(
        document_compiler, "_command", AsyncMock(return_value=(0, json.dumps(record).encode()))
    )
    compiler.destroy = AsyncMock(return_value=False)
    assert not await compiler.cleanup_recovered("a" * 64, ref, job)
    assert compiler._preparation_cleanup[job][1] == ("a" * 64 if owned else "gpthub-doc-" + job)
    assert compiler.destroy.await_count == int(owned)
    monkeypatch.setattr(
        document_compiler,
        "_command",
        AsyncMock(side_effect=[(1, b""), (0, b""), (0, b"")])
        if owned
        else AsyncMock(return_value=(0, b"")),
    )
    await compiler.reconcile()
    assert compiler.pending_preparation_cleanup == int(not owned)
