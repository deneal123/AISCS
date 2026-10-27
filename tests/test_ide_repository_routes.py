from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.infrastructure import workspace_client
from service.services.chat.application.ide.repositories import (
    IdeRepositoryIntentConflict,
    IdeRepositoryNotFound,
)
from service.services.chat.presentation.routers.chat_api.ide import repositories as api
from service.shared.repositories.exceptions import RepositoryOperationalError
from service.shared.security.auth_checker import check_auth


@pytest.fixture
def client_and_service(monkeypatch):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/chats")
    profile = SimpleNamespace(user_id=uuid4())
    service = SimpleNamespace(
        list=AsyncMock(return_value={"items": [], "next_offset": None}),
        get=AsyncMock(return_value={"state": "registered"}),
        register=AsyncMock(return_value={"state": "registered"}),
        ensure_default=AsyncMock(return_value={"state": "registered"}),
    )
    app.dependency_overrides[check_auth] = lambda: profile
    app.dependency_overrides[api.get_ide_repositories] = lambda: service
    create = AsyncMock(side_effect=AssertionError("Metadata must not allocate a sandbox"))
    monkeypatch.setattr(workspace_client, "ensure_workspace_explicit", create)
    with TestClient(app) as client:
        yield client, service, profile
    create.assert_not_awaited()


def test_auth_is_required_on_every_repository_route():
    app = FastAPI()
    app.include_router(api.router)
    routes = [route for route in app.routes if "/ide/repositories" in route.path]
    assert len(routes) == 4
    for route in routes:
        assert any(dependency.call is check_auth for dependency in route.dependant.dependencies)


def test_unauthenticated_requests_never_reach_repository_service():
    app = FastAPI()
    app.include_router(api.router, prefix="/api/chats")
    service = SimpleNamespace(list=AsyncMock(), get=AsyncMock(), register=AsyncMock())
    app.dependency_overrides[api.get_ide_repositories] = lambda: service
    path = f"/api/chats/{uuid4()}/ide/repositories"
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        assert client.post(f"{path}/default", json={}).status_code == 401
        assert client.get(f"{path}/{uuid4()}").status_code == 401
        assert (
            client.post(
                path,
                json={
                    "name": "Example",
                    "creation_intent_id": str(uuid4()),
                },
            ).status_code
            == 401
        )
    service.list.assert_not_awaited()
    service.get.assert_not_awaited()
    service.register.assert_not_awaited()


def test_list_uses_authenticated_owner_and_bounded_pagination(client_and_service):
    client, service, profile = client_and_service
    thread_id = uuid4()
    response = client.get(f"/api/chats/{thread_id}/ide/repositories?limit=10&offset=20")
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_offset": None}
    service.list.assert_awaited_once_with(
        thread_id=thread_id, user_id=profile.user_id, limit=10, offset=20
    )


def test_registration_normalizes_name_but_cannot_select_owner_or_workspace(client_and_service):
    client, service, profile = client_and_service
    thread_id, intent_id = uuid4(), uuid4()
    path = f"/api/chats/{thread_id}/ide/repositories"
    payload = {"name": "  Example  ", "creation_intent_id": str(intent_id)}
    response = client.post(path, json=payload)
    assert response.status_code == 200
    service.register.assert_awaited_once_with(
        thread_id=thread_id,
        user_id=profile.user_id,
        creation_intent_id=intent_id,
        name="Example",
        create_thread_if_missing=False,
    )
    for forbidden in (
        "user_id",
        "workspace_id",
        "root",
        "token",
        "remote_url",
        "onboarding_created",
    ):
        response = client.post(path, json={**payload, forbidden: "arbitrary"})
        assert response.status_code == 422
    assert service.register.await_count == 1


def test_default_identity_uses_server_scope_and_accepts_no_creation_policy(client_and_service):
    client, service, profile = client_and_service
    thread_id = uuid4()
    path = f"/api/chats/{thread_id}/ide/repositories/default"
    assert client.post(path, json={}).status_code == 200
    service.ensure_default.assert_awaited_once_with(thread_id=thread_id, user_id=profile.user_id)
    for field in ("user_id", "name", "onboarding_created", "creation_intent_id", "clear", "init"):
        assert client.post(path, json={field: "arbitrary"}).status_code == 422
    assert service.ensure_default.await_count == 1


@pytest.mark.parametrize(
    "failure,status", [(IdeRepositoryNotFound, 404), (RepositoryOperationalError, 503)]
)
def test_default_failure_is_not_retried_as_new_registration(client_and_service, failure, status):
    client, service, _ = client_and_service
    service.ensure_default.side_effect = failure("PRIVATE_DRIVER")
    response = client.post(f"/api/chats/{uuid4()}/ide/repositories/default", json={})
    assert response.status_code == status
    assert "PRIVATE" not in response.text
    service.register.assert_not_awaited()


def test_explicit_setup_passes_draft_creation_flag_without_allocating(client_and_service):
    client, service, _ = client_and_service
    response = client.post(
        f"/api/chats/{uuid4()}/ide/repositories",
        json={
            "name": "Project",
            "creation_intent_id": str(uuid4()),
            "create_thread_if_missing": True,
        },
    )
    assert response.status_code == 200
    assert service.register.await_args.kwargs["create_thread_if_missing"] is True


def test_get_uses_exact_repository_scope(client_and_service):
    client, service, profile = client_and_service
    thread_id, repository_id = uuid4(), uuid4()
    response = client.get(f"/api/chats/{thread_id}/ide/repositories/{repository_id}")
    assert response.status_code == 200
    service.get.assert_awaited_once_with(
        thread_id=thread_id, user_id=profile.user_id, repository_id=repository_id
    )


@pytest.mark.parametrize("suffix", ["?limit=0", "?limit=101", "?offset=-1", "?offset=100001"])
def test_invalid_pagination_never_reaches_persistence(client_and_service, suffix):
    client, service, _ = client_and_service
    assert client.get(f"/api/chats/{uuid4()}/ide/repositories{suffix}").status_code == 422
    service.list.assert_not_awaited()


@pytest.mark.parametrize(
    "failure,status,code",
    [
        (IdeRepositoryNotFound, 404, "ide_repository_not_found"),
        (IdeRepositoryIntentConflict, 409, "ide_repository_intent_conflict"),
        (RepositoryOperationalError, 503, "ide_repository_unavailable"),
    ],
)
def test_failures_are_not_empty_or_successful(client_and_service, failure, status, code):
    client, service, _ = client_and_service
    service.register.side_effect = failure("PRIVATE_DRIVER_DETAILS")
    response = client.post(
        f"/api/chats/{uuid4()}/ide/repositories",
        json={
            "name": "Example",
            "creation_intent_id": str(UUID(int=1)),
        },
    )
    assert response.status_code == status
    assert response.json() == {"detail": code}
    assert "PRIVATE" not in response.text
