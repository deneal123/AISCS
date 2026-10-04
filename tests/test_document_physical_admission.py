"""Orphans and unavailable inventory cannot disappear from compiler admission."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.admission import BuildAdmission
from application.documents.builds import DocumentBuildManager
from application.documents.projects import DocumentProjectError
from infrastructure import document_compiler
from infrastructure.document_compiler import CompilerFailure, DockerDocumentCompiler


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 32])
async def test_physical_orphans_without_manifest_block_before_container_allocation(count):
    compiler = DockerDocumentCompiler()
    compiler.inventory_refs = AsyncMock(return_value=frozenset(f"{i:064x}" for i in range(count)))
    manager = DocumentBuildManager(compiler, None, None, max_jobs=count)
    manager.recover = AsyncMock()
    manager._reserve_manifest = AsyncMock()
    manager._start_reserved = AsyncMock()
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await manager.start(
            None,
            SimpleNamespace(workspace_id="owned"),
            project_path="paper",
            expected_revision="rev",
            final=False,
        )
    manager._start_reserved.assert_not_awaited()
    compiler.inventory_refs.assert_awaited_once()
    assert manager._admission.preparing == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [CompilerFailure("runtime_unavailable"), OSError("private marker")]
)
async def test_inventory_failure_is_bounded_and_does_not_reserve_or_allocate(failure):
    compiler = DockerDocumentCompiler()
    compiler.inventory_refs = AsyncMock(side_effect=failure)
    manager = DocumentBuildManager(compiler, None, None)
    manager.recover = AsyncMock()
    manager._reserve_manifest = AsyncMock()
    manager._start_reserved = AsyncMock()
    with pytest.raises(DocumentProjectError, match="^runtime_unavailable$"):
        await manager.start(
            None,
            SimpleNamespace(workspace_id="owned"),
            project_path="paper",
            expected_revision="rev",
            final=False,
        )
    assert manager._admission.preparing == 0
    manager._start_reserved.assert_not_awaited()
    compiler.inventory_refs.assert_awaited_once()


@pytest.mark.asyncio
async def test_observed_union_deduplicates_live_reference_but_keeps_absent_cleanup_debt():
    compiler = DockerDocumentCompiler()
    compiler.inventory_refs = AsyncMock(return_value=frozenset({"a" * 64, "b" * 64}))
    manager = DocumentBuildManager(compiler, None, None)
    manager._builds = {
        "live": SimpleNamespace(compiler_ref="a" * 64),
        "missing": SimpleNamespace(compiler_ref="c" * 64),
    }
    assert await manager._observed_compiler_slots() == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,raw", [(1, b""), (0, b"malformed"), (0, b"a" * 64 + b"\n" + b"a" * 64), (0, b"\xff")]
)
async def test_native_inventory_rejects_unknown_or_incomplete_identifiers(monkeypatch, status, raw):
    monkeypatch.setattr(document_compiler, "_command", AsyncMock(return_value=(status, raw)))
    with pytest.raises(CompilerFailure, match="runtime_unavailable"):
        await DockerDocumentCompiler().inventory_refs()


@pytest.mark.asyncio
async def test_successful_empty_native_inventory_is_authoritative(monkeypatch):
    monkeypatch.setattr(document_compiler, "_command", AsyncMock(return_value=(0, b"")))
    assert await DockerDocumentCompiler().inventory_refs() == frozenset()


@pytest.mark.asyncio
async def test_observed_inventory_and_inflight_reservation_share_admission_budget():
    observed = AsyncMock(return_value=1)
    admission = BuildAdmission(2, lambda: 0, observed=observed)
    async with admission.reserve():
        with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
            async with admission.reserve():
                pytest.fail("overbooked physical capacity")
    assert admission.preparing == 0
