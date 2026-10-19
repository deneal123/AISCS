from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from presentation.routes.dependencies import WorkspaceRouteDependencies
from presentation.routes.ide_writes import create_ide_write_router


def fixture():
    @asynccontextmanager
    async def operation(item):
        yield

    writer = AsyncMock(return_value=dict(written=True))
    guard = AsyncMock(return_value=SimpleNamespace(allowed=True, fence=1))
    registry = SimpleNamespace(operation=operation, write_ide=writer)
    deps = WorkspaceRouteDependencies(
        auth=lambda value: None,
        error=lambda *args: None,
        registry=lambda: registry,
        owned=lambda *args: (object(), None),
        coordination_guard=guard,
        guard_denied=lambda value: False,
        run_file_op=None,
        revision=None,
        snapshot=None,
        fetch=None,
    )
    app = FastAPI()
    app.include_router(create_ide_write_router(deps))
    return TestClient(app), guard, writer


def test_agent_write_has_no_model_supplied_fence_and_uses_the_canonical_writer():
    client, guard, writer = fixture()
    body = dict(
        user_id="owner",
        token="private",
        path="main.py",
        operation="file",
        content="new",
        coordination_capability="capability",
    )
    response = client.post("/workspaces/owned/ide/agent/write", json=body)
    assert response.status_code == 200
    assert guard.await_args.args[0].coordination_fence is None
    assert guard.await_args.kwargs == dict(path="main.py", workspace_id="owned")
    assert writer.await_args.kwargs == dict(
        path="main.py", operation="file", content="new", expected_digest=None
    )


def test_ui_write_still_requires_fence_and_agent_cannot_inject_one():
    client, _, writer = fixture()
    body = dict(
        user_id="owner",
        token="private",
        path="main.py",
        operation="file",
        coordination_capability="capability",
    )
    assert client.post("/workspaces/owned/ide/write", json=body).status_code == 422
    assert (
        client.post(
            "/workspaces/owned/ide/agent/write", json={**body, "coordination_fence": 99}
        ).status_code
        == 422
    )
    assert (
        client.post("/workspaces/owned/ide/agent/write", json={**body, "command": "sh"}).status_code
        == 422
    )
    writer.assert_not_awaited()
