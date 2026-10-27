"""Auth, explicit actions, closed request bodies and bounded private errors."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.checkpoints.blob import IdeCheckpointError
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.presentation.routers.chat_api.ide import checkpoints as api
from service.shared.presentation.handlers.exceptions_handlers import setup_exception_handlers
from service.shared.repositories.exceptions import RepositoryOperationalError
from service.shared.security.auth_checker import check_auth


@pytest.fixture
def fixture():
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(api.router, prefix="/api/chats")
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    service = SimpleNamespace(
        **{
            name: AsyncMock(return_value={"state": "pending"})
            for name in (
                "history",
                "save",
                "status",
                "reconcile",
                "discard",
                "abandon",
                "restore",
                "restore_status",
                "reconcile_restore",
            )
        }
    )
    runtime = SimpleNamespace(_check_owner=AsyncMock())
    app.dependency_overrides[api.get_saved_projects] = lambda: service
    app.dependency_overrides[api.get_ide_runtime] = lambda: runtime
    path = f"/api/chats/{scope.thread_id}/ide/repositories/{scope.repository_id}"
    return app, service, runtime, scope, path


def test_every_checkpoint_action_requires_auth(fixture):
    app, service, runtime, _, path = fixture
    checkpoint, restore = uuid4(), uuid4()
    with TestClient(app) as client:
        for method, suffix, body in [
            ("GET", "/checkpoints/capabilities", None),
            ("GET", "/checkpoints", None),
            ("GET", f"/checkpoints/{checkpoint}", None),
            ("POST", "/checkpoints", {"checkpoint_id": str(checkpoint), "generation": "a" * 64}),
            ("POST", f"/checkpoints/{checkpoint}/reconcile", None),
            ("POST", f"/checkpoints/{checkpoint}/discard", None),
            ("POST", f"/checkpoints/{checkpoint}/abandon", None),
            (
                "POST",
                "/restores",
                {
                    "restore_id": str(restore),
                    "checkpoint_id": str(checkpoint),
                    "base_generation": "a" * 64,
                },
            ),
            ("GET", f"/restores/{restore}", None),
            ("POST", f"/restores/{restore}/reconcile", None),
        ]:
            assert client.request(method, path + suffix, json=body).status_code == 401
    for method in vars(service).values():
        method.assert_not_awaited()
    runtime._check_owner.assert_not_awaited()


def test_passive_status_and_explicit_reconcile_are_distinct_and_private(fixture):
    app, service, _, scope, path = fixture
    checkpoint = uuid4()
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    with TestClient(app) as client:
        response = client.get(path + f"/checkpoints/{checkpoint}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        service.reconcile.assert_not_awaited()
        service.save.assert_not_awaited()
        assert client.post(path + f"/checkpoints/{checkpoint}/reconcile").status_code == 200
    service.status.assert_awaited_once_with(scope, checkpoint)
    service.reconcile.assert_awaited_once_with(scope, checkpoint)


def test_save_and_restore_accept_only_public_intent_and_generation(fixture):
    app, service, _, scope, path = fixture
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    checkpoint, restore = uuid4(), uuid4()
    body = {"checkpoint_id": str(checkpoint), "base_checkpoint_id": None, "generation": "a" * 64}
    restore_body = {
        "restore_id": str(restore),
        "checkpoint_id": str(checkpoint),
        "base_generation": "a" * 64,
    }
    with TestClient(app) as client:
        assert (
            client.post(
                path + "/checkpoints",
                json=body,
                headers={"X-Workspace-Session": "actor-session-123456"},
            ).status_code
            == 200
        )
        assert client.post(path + "/restores", json=restore_body).status_code == 200
        for key in (
            "user_id",
            "allocation_id",
            "storage_namespace",
            "sha256",
            "size",
            "policy",
            "root",
        ):
            assert (
                client.post(path + "/checkpoints", json={**body, key: "arbitrary"}).status_code
                == 422
            )
            assert (
                client.post(path + "/restores", json={**restore_body, key: "arbitrary"}).status_code
                == 422
            )
    service.save.assert_awaited_once_with(
        scope,
        checkpoint_id=checkpoint,
        base_checkpoint_id=None,
        generation="a" * 64,
        session="actor-session-123456",
    )
    service.restore.assert_awaited_once_with(
        scope, restore_id=restore, checkpoint_id=checkpoint, base_generation="a" * 64
    )


@pytest.mark.parametrize(
    "error,status,code",
    [
        (RepositoryOperationalError("PRIVATE_DB"), 503, "ide_checkpoint_status_unknown"),
        (IdeRepositoryNotFound("PRIVATE_OWNER"), 404, "ide_repository_not_found"),
        (IdeCheckpointError("ide_checkpoint_quota_exceeded"), 409, "ide_checkpoint_quota_exceeded"),
        (
            IdeCheckpointError("ide_checkpoint_not_discardable"),
            409,
            "ide_checkpoint_not_discardable",
        ),
        (IdeCheckpointError("ide_checkpoint_head_changed"), 409, "ide_checkpoint_head_changed"),
        (
            IdeCheckpointError("ide_checkpoint_not_abandonable"),
            409,
            "ide_checkpoint_not_abandonable",
        ),
    ],
)
def test_private_failures_are_bounded_without_payload_or_empty_success(
    fixture, error, status, code
):
    app, service, _, scope, path = fixture
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    service.history.side_effect = error
    with TestClient(app) as client:
        response = client.get(path + "/checkpoints")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"] == code
    assert response.headers["cache-control"] == "private, no-store"
    assert "PRIVATE" not in response.text


def test_disabled_discovery_remains_passive_and_owned(fixture, monkeypatch):
    app, service, runtime, scope, path = fixture
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    monkeypatch.setattr(api.config.ide_checkpoints, "enabled", False)
    with TestClient(app) as client:
        assert client.get(path + "/checkpoints/capabilities").json() == {"enabled": False}
    runtime._check_owner.assert_awaited_once_with(scope)
    service.history.assert_not_awaited()


@pytest.mark.parametrize(
    "suffix,method",
    [
        ("checkpoints/{id}/reconcile", "reconcile"),
        ("checkpoints/{id}/discard", "discard"),
        ("checkpoints/{id}/abandon", "abandon"),
        ("restores/{id}/reconcile", "reconcile_restore"),
    ],
)
def test_recovery_actions_cannot_accept_private_override_claims(fixture, suffix, method):
    app, service, _, scope, path = fixture
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    with TestClient(app) as client:
        assert (
            client.post(
                path + "/" + suffix.format(id=uuid4()),
                json={"user_id": str(uuid4()), "force": True},
            ).status_code
            == 422
        )
    getattr(service, method).assert_not_awaited()


def test_checkpoint_routes_are_registered_in_the_actual_workspace_router():
    from service.services.chat.presentation.routers.chat_api.workspace.router import (
        workspace_router,
    )

    app = FastAPI()
    app.include_router(workspace_router, prefix="/api/chats")
    paths = app.openapi()["paths"]
    base = "/api/chats/{thread_id}/ide/repositories/{repository_id}"
    assert {"get", "post"}.issubset(paths[base + "/checkpoints"])
    assert "get" in paths[base + "/checkpoints/capabilities"]
    assert "post" in paths[base + "/restores"]
    assert "post" in paths[base + "/restores/{restore_id}/reconcile"]
