import hashlib
import json
import time
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest

from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.services.chat.domain.ide.files import IdeReadError
from service.services.chat.domain.ide.runtime import WorkspaceBinding
from tests.test_ide_workspace_client import settings

pytestmark = pytest.mark.asyncio


def binding():
    return WorkspaceBinding("a" * 32, "PRIVATE_TOKEN", int(time.time()) + 600)


async def test_file_transport_is_single_scoped_post_with_private_body():
    owner, value, calls = uuid4(), binding(), []
    path = "src/a'; echo nope.py"
    payload = {
        "path": path,
        "kind": "text",
        "size": 2,
        "content": "ok",
        "digest": hashlib.sha256(b"ok").hexdigest(),
        "truncated": False,
    }

    def handle(request):
        calls.append((request.method, request.url.path))
        assert json.loads(request.content) == {
            "user_id": str(owner),
            "token": value.token,
            "path": path,
        }
        assert request.headers["authorization"] == "Bearer PRIVATE_KEY"
        return httpx.Response(
            200, json={**payload, "root": "PRIVATE_ROOT", "token": "PRIVATE_TOKEN"}
        )

    result = await IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle)).read(
        owner, value, operation="file", path=path
    )
    assert result == payload
    assert calls == [("POST", f"/workspaces/{value.workspace_id}/ide/file")]


@pytest.mark.parametrize(
    "status,body,code",
    [
        (404, {"error": "workspace_not_found", "message": "PRIVATE"}, "ide_read_unavailable"),
        (403, {"error": "ide_path_forbidden", "message": "PRIVATE"}, "ide_path_forbidden"),
        (
            200,
            {"entries": [{"path": "x", "type": [], "size": 1}], "truncated": False},
            "ide_read_unavailable",
        ),
        (200, {"entries": [], "truncated": "no"}, "ide_read_unavailable"),
    ],
)
async def test_remote_error_or_bad_projection_is_closed_without_retry(status, body, code):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(status, json=body)

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    with pytest.raises(IdeReadError, match=code):
        await client.read(uuid4(), binding(), operation="tree", path="")
    assert len(calls) == 1


async def test_transport_failure_has_no_fallback_or_retry():
    calls = []

    def handle(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout("PRIVATE_BODY", request=request)

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    with pytest.raises(IdeReadError, match="ide_read_unavailable"):
        await client.read(uuid4(), binding(), operation="tree", path="")
    assert len(calls) == 1


async def test_expired_and_forbidden_inputs_never_reach_transport():
    def handle(_request):
        raise AssertionError("transport_must_not_run")

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    with pytest.raises(IdeReadError, match="ide_runtime_expired"):
        await client.read(uuid4(), replace(binding(), expires_at=1), operation="tree", path="")
    with pytest.raises(IdeReadError, match="ide_path_forbidden"):
        await client.read(uuid4(), binding(), operation="file", path="../secret")
