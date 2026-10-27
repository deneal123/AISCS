from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.services.chat.application.ide.prepare import IdePrepareService
from service.services.chat.domain.ide.edits import IdeEditError
from service.services.chat.presentation.routers.chat_api.ide import edits as api
from service.shared.security.auth_checker import check_auth
from tests.test_ide_edits import setup_runtime
from tests.test_workspace_collaboration import FakeRedis


@pytest.fixture
def prepared(monkeypatch):
    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "test-only-coordination-secret")
    scope, attempt, runtime = setup_runtime()
    descriptor = {"repository_id": scope.repository_id, "name": "Project", "created_at": None}
    runtime.repository = SimpleNamespace(
        ensure_default=AsyncMock(return_value=descriptor),
        get_owned=AsyncMock(return_value=descriptor),
        is_onboarding_owned=AsyncMock(return_value=True),
        is_clone_destination=AsyncMock(return_value=False),
    )
    runtime.provision = AsyncMock(
        return_value={
            "repository_id": str(scope.repository_id),
            "workspace": {"state": "ready", "expires_at": attempt.expires_at, "can_retry": False},
        }
    )
    runtime.client.git = AsyncMock(return_value={"initialized": True, "branch": "main"})
    return scope, attempt, runtime, IdePrepareService(runtime, FakeRedis())


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [None, "", "x", "a" * 65, "../arbitrary-session"])
async def test_invalid_entry_session_cannot_even_persist_a_draft(prepared, session):
    scope, _, runtime, service = prepared
    with pytest.raises(IdeEditError, match="ide_edit_session_required"):
        await service.prepare(thread_id=scope.thread_id, user_id=scope.user_id, session=session)
    runtime.repository.ensure_default.assert_not_awaited()
    runtime.provision.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_prepare_uses_owned_identity_and_non_retrying_runtime_before_git(prepared, explicit):
    scope, _, runtime, service = prepared
    result = await service.prepare(
        thread_id=scope.thread_id,
        user_id=scope.user_id,
        session="browser-session-0123456789",
        repository_id=scope.repository_id if explicit else None,
    )
    runtime.provision.assert_awaited_once_with(scope, allow_retry=False)
    (
        runtime.repository.get_owned if explicit else runtime.repository.ensure_default
    ).assert_awaited()
    if explicit:
        runtime.repository.ensure_default.assert_not_awaited()
    assert result["repository"]["repository_id"] == str(scope.repository_id)
    assert result["git"] == {"initialized": True, "branch": "main"}
    assert "PRIVATE" not in str(result)
    assert "generation" not in result
    assert runtime.client.git.await_args.kwargs["operation"] == "init"
    assert "replace_pristine_starter" not in runtime.client.git.await_args.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "unknown", "expired", "rejected", "unavailable"])
async def test_non_ready_preparation_keeps_same_project_and_never_initializes_git(prepared, state):
    scope, _, runtime, service = prepared
    runtime.provision.return_value["workspace"]["state"] = state
    result = await service.prepare(
        thread_id=scope.thread_id, user_id=scope.user_id, session="browser-session-0123456789"
    )
    assert result["runtime"]["workspace"]["state"] == state
    assert result["git"] is None
    runtime.client.git.assert_not_awaited()
    runtime.resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_ide_project_uses_idempotent_init_without_claiming_starter_provenance(
    prepared,
):
    scope, _, runtime, service = prepared
    runtime.repository.is_onboarding_owned.return_value = False
    result = await service.prepare(
        thread_id=scope.thread_id, user_id=scope.user_id, session="browser-session-0123456789"
    )
    assert result["git"] == {"initialized": True, "branch": "main"}
    assert runtime.client.git.await_args.kwargs["operation"] == "init"
    assert "replace_pristine_starter" not in runtime.client.git.await_args.kwargs
    runtime.repository.is_onboarding_owned.assert_not_awaited()


@pytest.mark.asyncio
async def test_entry_never_initializes_git_inside_a_clone_destination(prepared):
    scope, _, runtime, service = prepared
    runtime.repository.is_clone_destination.return_value = True
    result = await service.prepare(
        thread_id=scope.thread_id, user_id=scope.user_id, session="browser-session-0123456789"
    )
    assert result["runtime"]["workspace"]["state"] == "ready"
    assert result["git"] is None
    runtime.client.git.assert_not_awaited()


@pytest.mark.asyncio
async def test_git_failure_preserves_confirmed_identity_and_runtime(prepared):
    scope, _, runtime, service = prepared
    runtime.client.git.side_effect = IdeEditError("ide_git_unconfirmed")
    result = await service.prepare(
        thread_id=scope.thread_id, user_id=scope.user_id, session="browser-session-0123456789"
    )
    assert result["runtime"]["workspace"]["state"] == "ready"
    assert result["git_error"] == "ide_git_unconfirmed"
    assert result["git"] is None
    assert runtime.provision.await_count == 1


def test_prepare_route_is_authenticated_and_cannot_take_retry_or_clear_policy(prepared):
    scope, _, runtime, _ = prepared
    app = FastAPI()
    app.include_router(api.router, prefix="/api/chats")
    app.dependency_overrides[api.get_ide_runtime] = lambda: runtime
    app.dependency_overrides[api.get_optional_redis_client] = FakeRedis
    path = f"/api/chats/{scope.thread_id}/ide/prepare"
    with TestClient(app) as client:
        assert client.post(path, json={}).status_code == 401
        app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
        assert client.post(path, json={}).status_code == 422
        runtime.repository.ensure_default.assert_not_awaited()
        for key in ("user_id", "clear", "allow_retry", "onboarding_created", "workspace_id"):
            assert (
                client.post(
                    path,
                    json={key: True},
                    headers={"X-Workspace-Session": "browser-session-0123456789"},
                ).status_code
                == 422
            )
        runtime.repository.ensure_default.assert_not_awaited()
        assert (
            client.post(
                path, json={}, headers={"X-Workspace-Session": "browser-session-0123456789"}
            ).status_code
            == 200
        )
