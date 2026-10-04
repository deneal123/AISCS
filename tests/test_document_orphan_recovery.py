from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.builds import DocumentBuildManager
from infrastructure import document_compiler
from infrastructure.document_compiler import DockerDocumentCompiler


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [None, "workspace", "job", "contract", "kind"])
async def test_recovery_removes_only_matching_owned_compiler(monkeypatch, mismatch):
    compiler = DockerDocumentCompiler()
    compiler.destroy = AsyncMock(return_value=True)
    ref = SimpleNamespace(container_id="workspace-owned")
    labels = {
        "gpthub.document": "1",
        "gpthub.document.contract": "1",
        "gpthub.document.workspace_container": ref.container_id,
    }
    record = {"Name": "/gpthub-doc-build-owned", "Config": {"Labels": labels}}
    if mismatch == "workspace":
        labels["gpthub.document.workspace_container"] = "workspace-other"
    elif mismatch == "job":
        record["Name"] = "/gpthub-doc-build-other"
    elif mismatch == "contract":
        labels["gpthub.document.contract"] = "unknown"
    elif mismatch == "kind":
        labels["gpthub.document"] = "0"
    monkeypatch.setattr(
        document_compiler, "_command", AsyncMock(return_value=(0, json.dumps(record).encode()))
    )
    cleaned = await compiler.cleanup_recovered("a" * 64, ref, "build-owned")
    assert cleaned is (mismatch is None)
    assert compiler.destroy.await_count == int(mismatch is None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "inventory_status,inventory,expected", [(0, b"", True), (1, b"", False), (0, b"a" * 64, False)]
)
async def test_absence_is_proven_before_forgetting_cleanup(
    monkeypatch, inventory_status, inventory, expected
):
    compiler = DockerDocumentCompiler()
    command = AsyncMock(side_effect=[(1, b""), (inventory_status, inventory)])
    monkeypatch.setattr(document_compiler, "_command", command)
    assert (
        await compiler.cleanup_recovered("a" * 64, SimpleNamespace(container_id="ws"), "job")
        is expected
    )


@pytest.mark.asyncio
async def test_interrupted_cleanup_failure_is_retained_then_retried():
    compiler = SimpleNamespace(cleanup_recovered=AsyncMock(side_effect=[False, True]))
    manager = DocumentBuildManager(compiler, None, None)
    manager._persist = AsyncMock()
    build = SimpleNamespace(
        failure_code="build_interrupted", state="failed", compiler_ref="a" * 64, build_id="job"
    )
    item = SimpleNamespace(ref=SimpleNamespace(container_id="owned"))
    await manager._cleanup_interrupted_compiler(None, item, build)
    assert build.compiler_ref == "a" * 64
    manager._persist.assert_not_awaited()
    await manager._cleanup_interrupted_compiler(None, item, build)
    assert build.compiler_ref == ""
    manager._persist.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", ["failed", "cancelled", "ready", "preview_ready", "visual_pending"]
)
async def test_finished_compilation_cleanup_retries_for_every_outcome(state):
    compiler = SimpleNamespace(cleanup_recovered=AsyncMock(side_effect=[False, True]))
    manager = DocumentBuildManager(compiler, None, None)
    manager._persist = AsyncMock()
    build = SimpleNamespace(
        state=state,
        failure_code="compile_failed" if state == "failed" else "",
        compiler_ref="a" * 64,
        build_id="job",
    )
    item = SimpleNamespace(ref=SimpleNamespace(container_id="owned"))
    await manager._cleanup_interrupted_compiler(None, item, build)
    assert build.compiler_ref == "a" * 64
    await manager._cleanup_interrupted_compiler(None, item, build)
    assert build.compiler_ref == ""
    manager._persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_manifest_update_retains_cleanup_reference():
    from application.documents.projects import DocumentProjectError

    compiler = SimpleNamespace(cleanup_recovered=AsyncMock(return_value=True))
    manager = DocumentBuildManager(compiler, None, None)
    manager._persist = AsyncMock(side_effect=DocumentProjectError("workspace_unavailable"))
    build = SimpleNamespace(
        state="failed", failure_code="build_interrupted", compiler_ref="a" * 64, build_id="job"
    )
    item = SimpleNamespace(ref=SimpleNamespace(container_id="owned"))
    with pytest.raises(DocumentProjectError):
        await manager._cleanup_interrupted_compiler(None, item, build)
    assert build.compiler_ref == "a" * 64


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["building", "deterministic_audit", "publishing", "unknown"])
async def test_reconcile_does_not_remove_active_or_unknown_compilation(state):
    compiler = SimpleNamespace(cleanup_recovered=AsyncMock(return_value=True))
    manager = DocumentBuildManager(compiler, None, None)
    manager._persist = AsyncMock()
    build = SimpleNamespace(state=state, compiler_ref="a" * 64, build_id="job")
    await manager._cleanup_interrupted_compiler(None, SimpleNamespace(), build)
    compiler.cleanup_recovered.assert_not_awaited()
    manager._persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_preserves_compiler_while_live_task_is_finalizing():
    compiler = SimpleNamespace(cleanup_recovered=AsyncMock(return_value=True))
    manager = DocumentBuildManager(compiler, None, None)
    manager._persist = AsyncMock()
    manager._tasks["job"] = SimpleNamespace(done=lambda: False)
    build = SimpleNamespace(state="visual_pending", compiler_ref="a" * 64, build_id="job")
    await manager._cleanup_interrupted_compiler(None, SimpleNamespace(), build)
    compiler.cleanup_recovered.assert_not_awaited()
