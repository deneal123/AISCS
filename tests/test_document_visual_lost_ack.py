"""A post-write disconnect must be settled from the owned durable record."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.builds import DocumentBuildManager
from application.documents.projects import DocumentProjectError
from domain.documents import DocumentArtifact, DocumentBuild


def fixture():
    lock = asyncio.Lock()

    @asynccontextmanager
    async def operation(_item):
        async with lock:
            yield

    build = DocumentBuild(
        "job",
        "owned",
        "/workspace/paper",
        "generic_document",
        1,
        "rev",
        "d" * 64,
        "submission",
        True,
        state="visual_pending",
        artifacts=(
            DocumentArtifact(
                "pdf",
                "pdf",
                "document.pdf",
                "application/pdf",
                10,
                "a" * 64,
                "/workspace/paper/artifacts/document.pdf",
            ),
        ),
    )
    durable = {"value": build.manifest_dict()}
    manager = DocumentBuildManager(None, None, None)
    manager._recovered_workspaces.add("owned")
    manager._builds[build.build_id] = build

    async def save(_registry, _item, candidate):
        durable["value"] = candidate.manifest_dict()
        raise RuntimeError("PRIVATE-LOST-ACK")

    async def load(*_args):
        return (DocumentBuild.from_manifest(durable["value"]),)

    manager.store.save = AsyncMock(side_effect=save)
    manager.store.load = AsyncMock(side_effect=load)
    return (
        manager,
        SimpleNamespace(operation=operation),
        SimpleNamespace(workspace_id="owned", policy=SimpleNamespace(root="/workspace")),
        build,
        durable,
    )


async def complete(manager, registry, item, build):
    return await manager.complete_visual_audit(
        registry,
        item,
        build.build_id,
        source_digest=build.source_digest,
        artifact_sha256="a" * 64,
        passed=True,
        retryable=False,
        audit_version=1,
        diagnostics=[],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["claim", "complete", "cancel"])
async def test_post_write_lost_ack_settles_without_retrying_metadata_write(action):
    manager, registry, item, build, durable = fixture()
    if action == "claim":
        result = await manager.claim_visual_audit(registry, item, build.build_id)
    elif action == "cancel":
        result = await manager.cancel(registry, item, item.workspace_id, build.build_id)
    else:
        result = await complete(manager, registry, item, build)
    assert result is build
    assert build.manifest_dict() == durable["value"]
    manager.store.save.assert_awaited_once()
    manager.store.load.assert_awaited_once()


@pytest.mark.asyncio
async def test_unavailable_settlement_blocks_attestation_until_durable_cancel_is_read():
    manager, registry, item, build, durable = fixture()
    original_load = manager.store.load.side_effect
    manager.store.load.side_effect = RuntimeError("PRIVATE-LOOKUP")
    with pytest.raises(DocumentProjectError, match="^runtime_unavailable$"):
        await manager.cancel(registry, item, item.workspace_id, build.build_id)
    assert build.state == "visual_pending" and durable["value"]["state"] == "cancelled"
    with pytest.raises(DocumentProjectError, match="^runtime_unavailable$"):
        await complete(manager, registry, item, build)
    manager.store.save.assert_awaited_once()
    manager.store.load.side_effect = original_load
    with pytest.raises(DocumentProjectError, match="^audit_unavailable$"):
        await complete(manager, registry, item, build)
    assert build.state == "cancelled"
    manager.store.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_after_write_settles_on_next_find_without_repeating_call():
    manager, registry, item, build, durable = fixture()

    async def cancelled(*args):
        durable["value"] = args[-1].manifest_dict()
        raise asyncio.CancelledError()

    manager.store.save.side_effect = cancelled
    with pytest.raises(asyncio.CancelledError):
        await complete(manager, registry, item, build)
    assert build.state == "visual_pending"
    assert await manager.find(registry, item, build.build_id) is build
    assert build.state == "ready"
    manager.store.save.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("inventory", ["missing", "foreign", "changed_source"])
async def test_uncertain_record_cannot_be_replaced_by_missing_foreign_or_changed_identity(
    inventory,
):
    manager, registry, item, build, durable = fixture()
    manager.store.load.side_effect = RuntimeError("PRIVATE-LOOKUP")
    with pytest.raises(DocumentProjectError, match="^runtime_unavailable$"):
        await manager.cancel(registry, item, item.workspace_id, build.build_id)
    changed = dict(durable["value"])
    if inventory == "foreign":
        changed["workspace_id"] = "foreign"
    elif inventory == "changed_source":
        changed["source_digest"] = "e" * 64
    manager.store.load.side_effect = None
    manager.store.load.return_value = (
        () if inventory == "missing" else (DocumentBuild.from_manifest(changed),)
    )
    with pytest.raises(DocumentProjectError, match="^runtime_unavailable$"):
        await complete(manager, registry, item, build)
    assert build.state == "visual_pending"
    manager.store.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_reload_latest_build_resolves_lost_cancel_ack():
    manager, registry, item, build, _ = fixture()
    original_load = manager.store.load.side_effect
    manager.store.load.side_effect = RuntimeError("PRIVATE-LOOKUP")
    with pytest.raises(DocumentProjectError, match="^runtime_unavailable$"):
        await manager.cancel(registry, item, item.workspace_id, build.build_id)
    manager.store.load.side_effect = original_load
    assert await manager.latest_for_project(registry, item, "paper") is build
    assert build.state == "cancelled"
    manager.store.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconciliation_never_rewrites_unresolved_manifest_during_cleanup():
    manager, registry, item, build, _ = fixture()
    original_load = manager.store.load.side_effect
    manager.store.load.side_effect = RuntimeError("PRIVATE-LOOKUP")
    with pytest.raises(DocumentProjectError, match="^runtime_unavailable$"):
        await manager.cancel(registry, item, item.workspace_id, build.build_id)
    manager.compiler = SimpleNamespace(reconcile=AsyncMock())
    manager._cleanup_interrupted_compiler = AsyncMock()
    registry.active_workspaces = AsyncMock(return_value=(item,))
    await manager.reconcile_registry(registry)
    manager._cleanup_interrupted_compiler.assert_not_awaited()
    manager.store.save.assert_awaited_once()
    manager.store.load.side_effect = original_load
    await manager.reconcile_registry(registry)
    manager._cleanup_interrupted_compiler.assert_awaited_once_with(registry, item, build)
    assert build.state == "cancelled"
    manager.store.save.assert_awaited_once()


def test_uncertainty_marker_is_process_private_and_never_persisted_or_projected():
    _, _, _, build, _ = fixture()
    build.manifest_uncertain = True
    assert "manifest_uncertain" not in build.manifest_dict()
    assert "manifest_uncertain" not in build.public_dict()
    assert "manifest_uncertain" not in repr(build)
