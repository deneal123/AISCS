from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException

from service.services.chat.application.documents.assets import (
    confirmed_asset_import,
    document_asset_source,
)
from service.services.chat.application.workspace_collaboration import (
    CollaborationError,
    CollaborationUnavailable,
)
from service.services.chat.presentation.routers.chat_api.workspace import intake as routes
from service.services.chat.presentation.routers.chat_api.workspace.contracts import (
    LibraryCopyRequest,
)

FID = UUID("12345678-1234-1234-1234-123456789abc")
PATH = "documents/paper"
ASSET = f"figures/library_{FID.hex}.png"
DESTINATION = f"{PATH}/{ASSET}"


@asynccontextmanager
async def alive(*args):
    yield


@pytest.fixture
def runtime(monkeypatch):
    class Conflict(Exception):
        pass

    ref = {"user_id": "owner", "workspace_id": "private-workspace"}
    project = AsyncMock(return_value={"path": PATH, "revision": "r1"})
    imports = AsyncMock(
        return_value={
            "imported": 1,
            "kept": 0,
            "revision": "r2",
            "files": [{"name": DESTINATION, "outcome": "imported"}],
        }
    )
    client = SimpleNamespace(
        document_project_status=project, import_into_workspace=imports, WorkspaceConflict=Conflict
    )
    store = SimpleNamespace(
        preflight=AsyncMock(return_value={"fence": 7}),
        mark_stale=AsyncMock(),
        record_activity=AsyncMock(),
    )
    scope = SimpleNamespace(
        workspace_client=client,
        _ref=AsyncMock(return_value=ref),
        _request_ui_capability=lambda *args: "private-capability",
        verify_capability=lambda cap: cap,
        _collaboration=lambda *args: store,
        _alive=alive,
        CollaborationError=CollaborationError,
        CollaborationUnavailable=CollaborationUnavailable,
        _collaboration_http_error=lambda exc: HTTPException(status_code=503, detail="unavailable"),
    )
    monkeypatch.setattr(routes, "_runtime", lambda: scope)
    library = SimpleNamespace(
        resolve_chat_library_import=AsyncMock(
            return_value={
                "name": "Диаграмма.PNG",
                "url": "https://private-storage.invalid/secret-signed-url",
            }
        )
    )
    return SimpleNamespace(scope=scope, client=client, store=store, library=library)


async def copy(runtime, **kwargs):
    return await routes.copy_library_file_to_workspace(
        "thread",
        FID,
        LibraryCopyRequest(expected_revision="r1", fence=7, **kwargs),
        SimpleNamespace(user_id="owner"),
        SimpleNamespace(),
        runtime.library,
        None,
        "actor-session",
    )


@pytest.mark.asyncio
async def test_project_import_uses_owned_library_and_project_lease_without_leaking_capabilities(
    runtime,
):
    result = await copy(runtime, document_path=PATH)
    assert result == {"outcome": "imported", "revision": "r2", "asset_path": ASSET}
    runtime.library.resolve_chat_library_import.assert_awaited_once_with(
        "owner", FID, expiry_sec=120
    )
    assert runtime.store.preflight.call_args.kwargs == {
        "mutation": "import",
        "path": PATH,
        "fence": 7,
    }
    call = runtime.client.import_into_workspace.call_args
    assert call.args[1][0]["name"] == DESTINATION
    assert call.kwargs == {"expected_revision": "r1", "fence": 7}
    assert "url" not in repr(result) and "private" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "project,status",
    [
        (None, 404),
        ({"path": "documents/other", "revision": "r1"}, 404),
        ({"path": PATH, "revision": "r2"}, 409),
    ],
)
async def test_missing_foreign_or_stale_target_never_imports(runtime, project, status):
    runtime.client.document_project_status.return_value = project
    with pytest.raises(HTTPException) as failure:
        await copy(runtime, document_path=PATH)
    assert failure.value.status_code == status
    runtime.client.import_into_workspace.assert_not_awaited()
    runtime.store.preflight.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_thread_is_rejected_before_library_or_project_read(runtime):
    runtime.scope._ref.side_effect = HTTPException(status_code=404)
    with pytest.raises(HTTPException):
        await copy(runtime, document_path=PATH)
    runtime.library.resolve_chat_library_import.assert_not_awaited()
    runtime.client.document_project_status.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name", ["payload.tex", "archive.zip", "chart.svg", "chart.webp", "chart.gif"]
)
async def test_unsupported_document_material_cannot_be_advertised_as_figure(runtime, name):
    runtime.library.resolve_chat_library_import.return_value = {"name": name, "url": "private"}
    with pytest.raises(HTTPException) as failure:
        await copy(runtime, document_path=PATH)
    assert failure.value.status_code == 422
    runtime.client.import_into_workspace.assert_not_awaited()


@pytest.mark.asyncio
async def test_kept_project_asset_is_idempotent_and_not_recorded_as_new_import(runtime):
    runtime.client.import_into_workspace.return_value = {
        "imported": 0,
        "kept": 1,
        "revision": "r1",
        "files": [{"name": DESTINATION, "outcome": "kept"}],
    }
    assert await copy(runtime, document_path=PATH) == {
        "outcome": "kept",
        "revision": "r1",
        "asset_path": ASSET,
    }
    runtime.store.mark_stale.assert_not_awaited()


@pytest.mark.asyncio
async def test_aggregate_success_does_not_prove_that_the_target_asset_was_imported(runtime):
    runtime.client.import_into_workspace.return_value = {"imported": 1, "revision": "r2"}
    with pytest.raises(HTTPException) as failure:
        await copy(runtime, document_path=PATH)
    assert failure.value.status_code == 503
    runtime.store.mark_stale.assert_not_awaited()


@pytest.mark.asyncio
async def test_ordinary_work_copy_retains_original_name_and_does_not_read_document(runtime):
    result = await copy(runtime)
    assert result == {"outcome": "imported", "revision": "r2"}
    assert runtime.client.import_into_workspace.call_args.args[1][0]["name"] == "Диаграмма.PNG"
    runtime.client.document_project_status.assert_not_awaited()


@pytest.mark.parametrize("path", ["../outside", "a/../b", "/etc", "a\\b", "C:/x", "a//b", "a/./b"])
def test_document_destination_cannot_escape_project(path):
    with pytest.raises(ValueError):
        LibraryCopyRequest(expected_revision="r1", fence=1, document_path=path)


@pytest.mark.parametrize("files", [None, {}, [None], [{"name": "other", "outcome": "imported"}]])
def test_unconfirmed_asset_projection_fails_closed(files):
    assert not confirmed_asset_import({"files": files}, DESTINATION)


@pytest.mark.asyncio
async def test_owned_library_name_cannot_choose_destination_directories(runtime):
    source, asset = await document_asset_source(
        runtime.client,
        {},
        path=PATH,
        revision="r1",
        source={"name": "../../private/chart.png", "url": "private"},
        file_id=FID,
    )
    assert source["name"] == DESTINATION and asset == ASSET
