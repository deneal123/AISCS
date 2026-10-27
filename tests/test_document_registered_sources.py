from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from service.services.chat.application.documents import sources as sources
from service.services.chat.presentation.routers.chat_api.workspace import documents as routes
from service.services.chat.presentation.routers.chat_api.workspace.contracts import (
    DocumentPathRequest,
)


@pytest.fixture
def owned(monkeypatch):
    project = {"path": "documents/paper", "revision": "r1", "source_digest": "a" * 64}
    client = SimpleNamespace(
        document_project_status=AsyncMock(return_value=project),
        read_file=AsyncMock(return_value={"content": "bibliography"}),
    )
    rpc = SimpleNamespace(
        request_json=AsyncMock(return_value={"sources": [], "unresolved_count": 0})
    )
    monkeypatch.setattr(sources, "_client", lambda *_: rpc)
    return client, rpc, project


@pytest.mark.asyncio
async def test_read_is_project_owned_bounded_and_does_not_write(owned):
    client, rpc, project = owned
    result = await sources.read_owned_sources(
        client, {"workspace_id": "owned"}, project["path"], object()
    )
    assert result["revision"] == "r1"
    client.read_file.assert_awaited_once_with(
        {"workspace_id": "owned"}, "documents/paper/bibliography/references.bib"
    )
    rpc.request_json.assert_awaited_once_with(
        "POST", "/document-editor/sources", json_body={"bibliography": "bibliography"}
    )


@pytest.mark.asyncio
async def test_a_changed_project_rejects_the_read_instead_of_rebasing(owned):
    client, _, project = owned
    client.document_project_status.side_effect = [project, {**project, "source_digest": "b" * 64}]
    with pytest.raises(HTTPException) as failure:
        await sources.read_owned_sources(client, {}, project["path"], object())
    assert failure.value.status_code == 409


@pytest.mark.parametrize(
    "read", [None, {"content": "private", "truncated": True}, {"content": "я" * 375001}]
)
@pytest.mark.asyncio
async def test_partial_or_oversized_bibliography_never_reaches_parser(owned, read):
    client, rpc, project = owned
    client.read_file.return_value = read
    with pytest.raises(HTTPException):
        await sources.read_owned_sources(client, {}, project["path"], object())
    rpc.request_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_project_means_no_file_read(owned):
    client, rpc, _ = owned
    client.document_project_status.return_value = None
    with pytest.raises(HTTPException) as failure:
        await sources.read_owned_sources(client, {}, "documents/missing", object())
    assert failure.value.status_code == 404
    client.read_file.assert_not_awaited()
    rpc.request_json.assert_not_awaited()


@pytest.mark.parametrize(
    "path", ["/absolute", "../other", "documents/../other", "documents\\paper", "bad\x00path"]
)
@pytest.mark.asyncio
async def test_invalid_paths_cannot_reach_the_workspace(owned, path):
    client, rpc, _ = owned
    with pytest.raises(HTTPException) as failure:
        await sources.read_owned_sources(client, {}, path, object())
    assert failure.value.status_code == 422
    client.document_project_status.assert_not_awaited()
    client.read_file.assert_not_awaited()
    rpc.request_json.assert_not_awaited()


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"sources": [{"source_id": True}], "unresolved_count": 0},
        {"sources": [{"source_id": 1, "title": {"private": "data"}}], "unresolved_count": 0},
    ],
)
@pytest.mark.asyncio
async def test_invalid_private_reply_is_not_forwarded(owned, reply):
    client, rpc, project = owned
    rpc.request_json.return_value = reply
    with pytest.raises(HTTPException) as failure:
        await sources.read_owned_sources(client, {}, project["path"], object())
    assert failure.value.status_code == 503
    assert failure.value.detail == "document_sources_unavailable"


@pytest.mark.asyncio
async def test_response_projects_only_allowed_metadata(owned):
    client, rpc, project = owned
    rpc.request_json.return_value = {
        "sources": [
            {"source_id": 1, "title": "Actual", "key": "private-key", "raw": "unnecessary content"}
        ],
        "unresolved_count": 0,
        "private": "unnecessary envelope",
    }
    result = await sources.read_owned_sources(client, {}, project["path"], object())
    assert result["sources"] == [{"source_id": 1, "title": "Actual"}]
    assert "private" not in result


@pytest.mark.asyncio
async def test_ownership_is_checked_before_any_sources_access(monkeypatch):
    denied = AsyncMock(side_effect=HTTPException(status_code=403))
    read = AsyncMock()
    monkeypatch.setattr(routes, "_runtime", lambda: SimpleNamespace(_ref=denied))
    monkeypatch.setattr(sources, "read_owned_sources", read)
    with pytest.raises(HTTPException) as failure:
        await routes.document_registered_sources(
            "foreign",
            DocumentPathRequest(path="documents/paper"),
            SimpleNamespace(user_id=7),
            object(),
            None,
        )
    assert failure.value.status_code == 403
    read.assert_not_awaited()
