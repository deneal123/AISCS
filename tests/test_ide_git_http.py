from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from presentation.routes.dependencies import WorkspaceRouteDependencies
from presentation.routes.ide_git import create_ide_git_router


def fixture():
    @asynccontextmanager
    async def operation(item):
        yield

    git = AsyncMock(return_value={"initialized": True, "branch": "main"})
    guard = AsyncMock(return_value=SimpleNamespace(allowed=True))
    registry = SimpleNamespace(operation=operation, git_ide=git)
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
    app.include_router(create_ide_git_router(deps))
    return TestClient(app), guard, git


def test_private_git_policy_is_strict_and_uses_existing_operation_guard():
    client, guard, git = fixture()
    payload = {
        "user_id": "owner",
        "token": "private",
        "operation": "clone",
        "coordination_capability": "signed",
        "replace_pristine_starter": True,
    }
    for invalid in (1, "true", {}, None):
        assert (
            client.post(
                "/workspaces/id/ide/git", json={**payload, "replace_pristine_starter": invalid}
            ).status_code
            == 422
        )
    guard.assert_not_awaited()
    git.assert_not_awaited()
    assert client.post("/workspaces/id/ide/git", json=payload).status_code == 200
    assert guard.await_args.args[1] == "snapshot"
    assert git.await_args.kwargs["replace_pristine_starter"] is True
