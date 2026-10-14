"""Registry commands must acknowledge completion, not merely omit an error."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.build_store import BuildManifestStore
from application.documents.builds import DocumentBuildManager
from application.documents.projects import DocumentProjectError
from domain.documents import DocumentBuild


def fixture():
    item = SimpleNamespace(workspace_id="owned", policy=SimpleNamespace(root="/workspace"))
    build = DocumentBuild(
        "job",
        "owned",
        "/workspace/paper",
        "generic_document",
        1,
        "rev",
        "d" * 64,
        "draft",
        False,
    )
    return item, build


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["load", "save", "delete"])
@pytest.mark.parametrize("code", [None, False, "0"])
async def test_missing_or_coerced_exit_code_never_acknowledges_registry_operation(operation, code):
    item, build = fixture()
    payload = json.dumps(
        build.manifest_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    outputs = {
        "load": "__GPTHUB_MANIFESTS_COMPLETE__\n",
        "save": f"__OK__ {len(payload.encode('utf-8'))}\n",
        "delete": "__OK__\n",
    }
    registry = SimpleNamespace(
        exec_raw=AsyncMock(
            return_value=SimpleNamespace(
                stdout=outputs[operation],
                exit_code=code,
                truncated=False,
                timed_out=False,
            )
        )
    )
    with pytest.raises(RuntimeError):
        if operation == "load":
            await BuildManifestStore().load(registry, item)
        elif operation == "save":
            await BuildManifestStore().save(registry, item, build)
        else:
            await BuildManifestStore().delete(registry, item, build.build_id)
    registry.exec_raw.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["", "\n", "{}\n", "__GPTHUB_MANIFESTS_COMPLETE__"])
async def test_inventory_without_complete_frame_is_not_empty_success(body):
    item, _ = fixture()
    registry = SimpleNamespace(
        exec_raw=AsyncMock(
            return_value=SimpleNamespace(
                stdout=body,
                exit_code=0,
                truncated=False,
                timed_out=False,
            )
        )
    )
    with pytest.raises(RuntimeError, match="^build manifest inventory unavailable$"):
        await BuildManifestStore().load(registry, item)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["save", "delete"])
@pytest.mark.parametrize("body", ["PRIVATE __OK__\n", "__OK__", "__OK__ 0\n"])
async def test_embedded_incomplete_or_wrong_size_write_marker_is_not_confirmation(operation, body):
    item, build = fixture()
    registry = SimpleNamespace(
        exec_raw=AsyncMock(
            return_value=SimpleNamespace(
                stdout=body,
                exit_code=0,
                truncated=False,
                timed_out=False,
            )
        )
    )
    with pytest.raises(RuntimeError):
        if operation == "save":
            await BuildManifestStore().save(registry, item, build)
        else:
            await BuildManifestStore().delete(registry, item, build.build_id)


@pytest.mark.asyncio
async def test_unacknowledged_empty_inventory_leaves_recovery_pending_until_explicit_retry():
    @asynccontextmanager
    async def operation(_item):
        yield

    item, _ = fixture()
    registry = SimpleNamespace(
        operation=operation,
        exec_raw=AsyncMock(
            return_value=SimpleNamespace(
                stdout="",
                exit_code=0,
                truncated=False,
                timed_out=False,
            )
        ),
    )
    manager = DocumentBuildManager(None, None, None)
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await manager.recover(registry, item)
    assert "owned" in manager._pending_recovery
    assert "owned" not in manager._recovered_workspaces
    assert not manager._builds
    registry.exec_raw.return_value.stdout = "__GPTHUB_MANIFESTS_COMPLETE__\n"
    await manager.recover(registry, item)
    assert "owned" in manager._recovered_workspaces
    assert "owned" not in manager._pending_recovery
    assert registry.exec_raw.await_count == 2


@pytest.mark.asyncio
async def test_confirmed_inventory_save_and_delete_accept_exact_command_receipts():
    item, build = fixture()
    payload = json.dumps(
        build.manifest_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    registry = SimpleNamespace(
        exec_raw=AsyncMock(
            side_effect=[
                SimpleNamespace(stdout=payload + "\n__GPTHUB_MANIFESTS_COMPLETE__\n", exit_code=0),
                SimpleNamespace(stdout=f"__OK__ {len(payload.encode('utf-8'))}\n", exit_code=0),
                SimpleNamespace(stdout="__OK__\n", exit_code=0),
            ]
        )
    )
    store = BuildManifestStore()
    records = await store.load(registry, item)
    assert len(records) == 1 and records[0].manifest_dict() == build.manifest_dict()
    await store.save(registry, item, build)
    await store.delete(registry, item, build.build_id)
    assert registry.exec_raw.await_count == 3
