"""Visual state is observable only after its durable acknowledgement."""

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
        "audit-job",
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
    manager = DocumentBuildManager(None, None, None)
    manager.recover = AsyncMock()
    manager._builds[build.build_id] = build
    manager.store.save = AsyncMock()
    manager.store.load = AsyncMock(
        side_effect=lambda *_args: (DocumentBuild.from_manifest(build.manifest_dict()),)
    )
    registry = SimpleNamespace(operation=operation)
    item = SimpleNamespace(workspace_id="owned")
    return manager, registry, item, build


async def complete(manager, registry, item, build, **changes):
    return await manager.complete_visual_audit(
        registry,
        item,
        build.build_id,
        source_digest=build.source_digest,
        artifact_sha256="a" * 64,
        passed=changes.get("passed", True),
        retryable=changes.get("retryable", False),
        audit_version=1,
        diagnostics=changes.get("diagnostics", []),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["claim", "passed", "failed", "retryable", "cancel"])
async def test_failed_acknowledgement_preserves_observed_and_durable_state(action):
    manager, registry, item, build = fixture()
    if action in {"passed", "failed", "retryable"}:
        build.state = "visual_audit"
        build.visual_audit_claimed_at = 123.0
    before = build.manifest_dict()
    manager.store.save.side_effect = RuntimeError("PRIVATE-RESPONSE")
    with pytest.raises(DocumentProjectError, match="^runtime_unavailable$"):
        if action == "claim":
            await manager.claim_visual_audit(registry, item, build.build_id)
        elif action == "cancel":
            await manager.cancel(registry, item, item.workspace_id, build.build_id)
        else:
            await complete(
                manager,
                registry,
                item,
                build,
                passed=action == "passed",
                retryable=action == "retryable",
            )
    assert build.manifest_dict() == before
    assert manager.get(item.workspace_id, build.build_id) is build
    assert manager.manifest_failures == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["claim", "complete", "cancel"])
async def test_pending_manifest_write_never_exposes_uncommitted_state(action):
    manager, registry, item, build = fixture()
    before = build.manifest_dict()
    entered, release = asyncio.Event(), asyncio.Event()

    async def save(_registry, _item, candidate):
        assert candidate is not build
        entered.set()
        await release.wait()

    manager.store.save.side_effect = save
    if action == "claim":
        coroutine = manager.claim_visual_audit(registry, item, build.build_id)
    elif action == "cancel":
        coroutine = manager.cancel(registry, item, item.workspace_id, build.build_id)
    else:
        coroutine = complete(manager, registry, item, build)
    task = asyncio.create_task(coroutine)
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert build.manifest_dict() == before
        release.set()
        assert await asyncio.wait_for(task, 1) is build
        assert (
            build.state
            == {"claim": "visual_audit", "complete": "ready", "cancel": "cancelled"}[action]
        )
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_wins_against_attestation_waiting_for_same_operation_guard():
    manager, registry, item, build = fixture()
    entered, release = asyncio.Event(), asyncio.Event()

    async def save(*_args):
        entered.set()
        await release.wait()

    manager.store.save.side_effect = save
    cancel = asyncio.create_task(manager.cancel(registry, item, item.workspace_id, build.build_id))
    finish = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        finish = asyncio.create_task(complete(manager, registry, item, build))
        await asyncio.sleep(0)
        release.set()
        assert await asyncio.wait_for(cancel, 1) is build
        with pytest.raises(DocumentProjectError, match="^audit_unavailable$"):
            await asyncio.wait_for(finish, 1)
        assert build.state == "cancelled"
        manager.store.save.assert_awaited_once()
    finally:
        release.set()
        for task in (cancel, finish):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (cancel, finish) if task is not None), return_exceptions=True
        )


@pytest.mark.asyncio
async def test_interrupted_manifest_write_keeps_prior_visual_state():
    manager, registry, item, build = fixture()
    before = build.manifest_dict()
    manager.store.save.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await complete(manager, registry, item, build)
    assert build.manifest_dict() == before


@pytest.mark.asyncio
async def test_concurrent_claims_persist_once_and_second_claim_is_busy():
    manager, registry, item, build = fixture()
    results = await asyncio.gather(
        manager.claim_visual_audit(registry, item, build.build_id),
        manager.claim_visual_audit(registry, item, build.build_id),
        return_exceptions=True,
    )
    assert results[0] is build
    assert isinstance(results[1], DocumentProjectError) and results[1].code == "audit_busy"
    assert build.state == "visual_audit"
    manager.store.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeat_completion_is_rejected_without_second_persistence():
    manager, registry, item, build = fixture()
    assert await complete(manager, registry, item, build) is build
    with pytest.raises(DocumentProjectError, match="^audit_unavailable$"):
        await complete(manager, registry, item, build)
    manager.store.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_claim_can_retry_without_busy_state_or_replacing_identity():
    manager, registry, item, build = fixture()
    manager.store.save.side_effect = [RuntimeError("PRIVATE-RESPONSE"), None]
    with pytest.raises(DocumentProjectError, match="^runtime_unavailable$"):
        await manager.claim_visual_audit(registry, item, build.build_id)
    assert await manager.claim_visual_audit(registry, item, build.build_id) is build
    assert build.state == "visual_audit"
    assert manager.store.save.await_count == 2
