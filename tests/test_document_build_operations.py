"""Повтор и рестарт наблюдают тот же build; intent без manifest запрещает create."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from application.documents import builds
from application.documents.build_store import BuildManifestStore
from application.documents.builds import DocumentBuildManager
from application.documents.projects import DocumentProjectError
from domain.documents import DocumentBuild
from domain.documents.document_review import operation_build_id
from infrastructure.document_compiler import PreparedCompilerJob
from test_document_build_manager import _Compiler, _Projects, _Registry


class Compiler(_Compiler):
    def __init__(self):
        super().__init__()
        self.creates = 0

    async def prepare(self, *_args, **kwargs):
        self.creates += 1
        job = PreparedCompilerJob(kwargs["job_ref"], "container-private", "paper")
        await kwargs["before_create"](job.job_ref)
        await kwargs["on_allocated"](job)
        return job


class Store:
    def __init__(self):
        self.values = {}

    async def save(self, _registry, _item, build):
        self.values[build.build_id] = deepcopy(build.manifest_dict())

    async def load(self, _registry, _item):
        return tuple(DocumentBuild.from_manifest(raw) for raw in self.values.values())

    async def verify_artifacts(self, *_args):
        return True

    prune_candidates = staticmethod(BuildManifestStore.prune_candidates)


def fixture():
    compiler, registry, store = Compiler(), _Registry(), Store()
    item = SimpleNamespace(
        workspace_id="workspace-1",
        ref=SimpleNamespace(container_id="workspace-container"),
        policy=SimpleNamespace(root="/workspace"),
    )
    manager = DocumentBuildManager(compiler, _Projects(), AsyncMock(return_value="r1"), store=store)
    spec = dict(
        project_path="paper",
        expected_revision="r1",
        final=True,
        operation_id=str(uuid4()),
    )
    return manager, compiler, registry, store, item, spec


@pytest.mark.asyncio
async def test_concurrent_replay_and_restart_keep_one_compiler_and_same_manifest(monkeypatch):
    manager, compiler, registry, store, item, spec = fixture()
    claim = AsyncMock(return_value=True)
    monkeypatch.setattr(builds, "claim_operation", claim)
    first, second = await asyncio.gather(
        manager.start(registry, item, **spec),
        manager.start(registry, item, **spec),
    )
    assert first is second and compiler.creates == claim.await_count == 1
    assert first.build_id == operation_build_id(item.workspace_id, spec["operation_id"])
    await manager._tasks[first.build_id]
    restored_compiler = Compiler()
    restored = DocumentBuildManager(
        restored_compiler,
        _Projects(),
        AsyncMock(return_value="user-new-revision"),
        store=store,
    )
    replay = await restored.start(registry, item, **spec)
    assert replay.manifest_dict() == first.manifest_dict()
    assert restored_compiler.creates == 0 and claim.await_count == 1
    assert "operation_id" not in replay.public_dict()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        {"project_path": "other"},
        {"expected_revision": "r2"},
        {"final": False},
    ],
)
async def test_same_operation_with_changed_recipe_is_rejected(monkeypatch, changed):
    manager, compiler, registry, _, item, spec = fixture()
    monkeypatch.setattr(builds, "claim_operation", AsyncMock(return_value=True))
    first = await manager.start(registry, item, **spec)
    await manager._tasks[first.build_id]
    with pytest.raises(DocumentProjectError, match="source_changed"):
        await manager.start(registry, item, **{**spec, **changed})
    assert compiler.creates == 1


@pytest.mark.asyncio
async def test_claim_without_manifest_after_crash_never_authorizes_a_second_create(monkeypatch):
    manager, compiler, registry, _, item, spec = fixture()
    claim = AsyncMock(return_value=False)
    monkeypatch.setattr(builds, "claim_operation", claim)
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await manager.start(registry, item, **spec)
    assert compiler.creates == 0 and not manager._builds


@pytest.mark.asyncio
async def test_invalid_operation_never_dispatches_or_claims(monkeypatch):
    manager, compiler, registry, _, item, spec = fixture()
    claim = AsyncMock()
    monkeypatch.setattr(builds, "claim_operation", claim)
    with pytest.raises(DocumentProjectError, match="invalid_project"):
        await manager.start(registry, item, **{**spec, "operation_id": "arbitrary-shell;value"})
    assert compiler.creates == 0
    claim.assert_not_awaited()


def test_operation_receipt_is_not_evicted_and_identity_is_environment_scoped():
    operation = str(uuid4())
    first = operation_build_id("one", operation)
    assert first != operation_build_id("two", operation)
    build = DocumentBuild(
        build_id=first,
        operation_id=operation,
        workspace_id="one",
        project_path="/workspace/paper",
        profile_id="generic_article",
        profile_version=1,
        source_revision="r1",
        source_digest="a" * 64,
        mode="draft",
        final=False,
        state="failed",
        created_at=1,
    )
    assert BuildManifestStore.prune_candidates((build,), now=1_000_000) == ()
    assert DocumentBuild.from_manifest(build.manifest_dict()).operation_id == operation
    corrupt = {**build.manifest_dict(), "operation_id": str(uuid4())}
    with pytest.raises(ValueError, match="invalid build operation"):
        DocumentBuild.from_manifest(corrupt)
