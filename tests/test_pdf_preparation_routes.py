from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from service.services.chat.domain.documents.preparation import (
    PdfPreparationNotFound,
    PdfPreparationScope,
    PdfPreparationUnavailable,
)
from service.services.chat.presentation.routers.chat_api import pdf_preparation_routes as api
from service.shared.presentation.handlers.exceptions_handlers import http_exception_handler
from service.shared.repositories.exceptions import RepositoryOperationalError
from service.shared.security.auth_checker import check_auth


@pytest.fixture
def setup():
    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.include_router(api.router, prefix="/api/chats")
    scope = PdfPreparationScope(uuid4(), uuid4())
    service = SimpleNamespace(prepare=AsyncMock(return_value={"state": "ready"}))
    app.dependency_overrides[api.get_pdf_preparation] = lambda: service
    return app, scope, service


def test_prepare_requires_auth_before_any_preparation(setup):
    app, scope, service = setup
    with TestClient(app) as client:
        assert (
            client.post(f"/api/chats/{scope.thread_id}/work/pdf/prepare", json={}).status_code
            == 401
        )
    service.prepare.assert_not_awaited()


def test_scope_and_defaults_are_server_owned_and_get_cannot_prepare(setup):
    app, scope, service = setup
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    path = f"/api/chats/{scope.thread_id}/work/pdf/prepare"
    with TestClient(app) as client:
        assert client.get(path).status_code == 405
        for key in ("user_id", "workspace_id", "allocation_id", "expires_at", "path", "profile_id"):
            assert client.post(path, json={key: "arbitrary"}).status_code == 422
        assert client.post(path, json={}).json() == {"state": "ready"}
    service.prepare.assert_awaited_once_with(scope, retry_scaffold=False)


def test_scaffold_retry_requires_an_explicit_boolean_not_an_entry_replay(setup):
    app, scope, service = setup
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    path = f"/api/chats/{scope.thread_id}/work/pdf/prepare"
    with TestClient(app) as client:
        assert client.post(path, json={"retry": True}).status_code == 200
        for value in ("true", 1, None):
            assert client.post(path, json={"retry": value}).status_code == 422
    service.prepare.assert_awaited_once_with(scope, retry_scaffold=True)


@pytest.mark.parametrize(
    "error,status,code",
    [
        (PdfPreparationNotFound, 404, "pdf_project_not_found"),
        (PdfPreparationUnavailable, 503, "pdf_preparation_unavailable"),
        (RepositoryOperationalError, 503, "pdf_preparation_unavailable"),
    ],
)
def test_failure_does_not_leak_private_diagnostics_or_claim_ready(setup, error, status, code):
    app, scope, service = setup
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    service.prepare.side_effect = error("PRIVATE_BODY")
    with TestClient(app) as client:
        response = client.post(f"/api/chats/{scope.thread_id}/work/pdf/prepare", json={})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "PRIVATE" not in response.text
