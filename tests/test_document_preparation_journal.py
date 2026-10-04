"""Crash-safe compiler allocation intent and owner-bound recovery."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.build_preparation import prepare_build
from application.documents.builds import DocumentBuildManager
from application.documents.projects import DocumentProjectError
from domain.documents import load_profile_catalog
from infrastructure import document_compiler
from infrastructure.document_compiler import CompilerFailure, DockerDocumentCompiler


@asynccontextmanager
async def operation(_item):
    yield


def fixture():
    compiler = DockerDocumentCompiler()
    compiler._validate_source = AsyncMock()
    compiler.destroy = AsyncMock(return_value=False)
    item = SimpleNamespace(
        workspace_id="owned",
        ref=SimpleNamespace(container_id="source"),
        policy=SimpleNamespace(root="/workspace"),
    )
    projects = SimpleNamespace(
        manifest=AsyncMock(return_value=({}, load_profile_catalog().get("generic_article"))),
        digest=AsyncMock(return_value="d" * 64),
    )
    manager = DocumentBuildManager(compiler, projects, AsyncMock(return_value="rev"))
    registry = SimpleNamespace(operation=operation)
    return manager, registry, item


@pytest.mark.asyncio
async def test_intent_and_exact_id_are_durable_before_create_and_staging(monkeypatch):
    manager, registry, item = fixture()
    manifests = []

    async def save(_registry, _item, build):
        manifests.append(build.manifest_dict())

    manager.store.save = AsyncMock(side_effect=save)

    async def command(*args, **_kwargs):
        if args[1] == "create":
            assert manifests[-1]["state"] == "preparing"
            assert manifests[-1]["compiler_ref"].startswith("gpthub-doc-")
            return 0, b"a" * 64
        assert manifests[-1]["compiler_ref"] == "a" * 64
        return 0, b""

    async def pipe(*_args, **_kwargs):
        assert manifests[-1]["compiler_ref"] == "a" * 64

    monkeypatch.setattr(document_compiler, "_command", command)
    monkeypatch.setattr(document_compiler, "_pipe", pipe)
    build, prepared, _ = await prepare_build(
        manager, registry, item, project_path="paper", expected_revision="rev", final=False
    )
    assert build.compiler_ref == prepared.container_id == "a" * 64
    assert len(manifests) == 2


@pytest.mark.asyncio
async def test_failed_intent_save_never_creates_container(monkeypatch):
    manager, registry, item = fixture()
    manager.store.save = AsyncMock(side_effect=RuntimeError("private-marker"))
    command = AsyncMock()
    monkeypatch.setattr(document_compiler, "_command", command)
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await prepare_build(
            manager, registry, item, project_path="paper", expected_revision="rev", final=False
        )
    command.assert_not_awaited()
    assert manager._occupied_compiler_slots() == 0


@pytest.mark.asyncio
async def test_unknown_create_preserves_durable_name_after_process_replacement(monkeypatch):
    manager, registry, item = fixture()
    manifests = []

    async def save(_registry, _item, build):
        manifests.append(build.manifest_dict())

    manager.store.save = AsyncMock(side_effect=save)
    monkeypatch.setattr(
        document_compiler, "_command", AsyncMock(side_effect=CompilerFailure("runtime_unavailable"))
    )
    with pytest.raises(CompilerFailure):
        await prepare_build(
            manager, registry, item, project_path="paper", expected_revision="rev", final=False
        )
    assert manifests[0]["state"] == "preparing"
    recovered = type(next(iter(manager._builds.values()))).from_manifest(manifests[-1])
    replacement = DocumentBuildManager(DockerDocumentCompiler(), None, None)
    replacement._builds[recovered.build_id] = recovered
    replacement._persist = AsyncMock()
    monkeypatch.setattr(document_compiler, "_command", AsyncMock(return_value=(1, b"")))
    await replacement._cleanup_interrupted_compiler(registry, item, recovered)
    assert recovered.compiler_ref.startswith("gpthub-doc-")
    assert replacement._occupied_compiler_slots() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["source", "foreign"])
async def test_recovered_name_promotes_only_verified_owner_before_cleanup(monkeypatch, owner):
    manager, registry, item = fixture()
    build = SimpleNamespace(
        build_id="owned-build", state="failed", compiler_ref="gpthub-doc-owned-build"
    )
    record = {
        "Id": "a" * 64,
        "Name": "/gpthub-doc-owned-build",
        "Config": {
            "Labels": {
                "gpthub.document": "1",
                "gpthub.document.contract": "1",
                "gpthub.document.workspace_container": owner,
            }
        },
    }
    monkeypatch.setattr(
        document_compiler, "_command", AsyncMock(return_value=(0, json.dumps(record).encode()))
    )
    manager._persist = AsyncMock()
    manager.compiler.cleanup_recovered = AsyncMock(return_value=False)
    await manager._cleanup_interrupted_compiler(registry, item, build)
    assert build.compiler_ref == ("a" * 64 if owner == "source" else "gpthub-doc-owned-build")
    assert manager.compiler.cleanup_recovered.await_count == int(owner == "source")
    assert manager._persist.await_count == int(owner == "source")


@pytest.mark.asyncio
async def test_failed_exact_id_write_preserves_cleanup_reference(monkeypatch):
    manager, registry, item = fixture()
    manager.store.save = AsyncMock(side_effect=[None, RuntimeError("private-marker"), None])
    manager.compiler.cleanup_recovered = AsyncMock(return_value=False)
    monkeypatch.setattr(document_compiler, "_command", AsyncMock(return_value=(0, b"a" * 64)))
    pipe = AsyncMock()
    monkeypatch.setattr(document_compiler, "_pipe", pipe)
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await prepare_build(
            manager, registry, item, project_path="paper", expected_revision="rev", final=False
        )
    pipe.assert_not_awaited()
    build = next(iter(manager._builds.values()))
    assert build.state == "failed" and build.compiler_ref == "a" * 64
    manager.compiler.destroy.assert_awaited_once_with("a" * 64)


@pytest.mark.asyncio
async def test_failed_recovered_promotion_write_does_not_destroy_or_forget_name():
    manager, registry, item = fixture()
    build = SimpleNamespace(
        build_id="owned-build", state="failed", compiler_ref="gpthub-doc-owned-build"
    )
    manager.compiler.resolve_owned_preparation = AsyncMock(return_value="a" * 64)
    manager.compiler.cleanup_recovered = AsyncMock()
    manager._persist = AsyncMock(side_effect=DocumentProjectError("runtime_unavailable"))
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await manager._cleanup_interrupted_compiler(registry, item, build)
    assert build.compiler_ref == "gpthub-doc-owned-build"
    manager.compiler.cleanup_recovered.assert_not_awaited()
