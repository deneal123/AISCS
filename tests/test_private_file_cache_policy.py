"""Private file capabilities and metadata must not enter browser/shared caches."""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.responses import Response

from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.presentation.routers.files_api.private_route import PrivateFileRoute
from service.shared.presentation.handlers.exceptions_handlers import setup_exception_handlers
from tests.test_file_download_ownership import fixture_app


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["download", "modes", "missing", "anonymous"])
@pytest.mark.parametrize("production_handlers", [False, True])
async def test_file_responses_are_private_and_not_stored(kind, production_handlers):
    app, service, _ = fixture_app(authenticated=kind != "anonymous")
    if production_handlers:
        setup_exception_handlers(app)
    if kind == "download":
        service.get_owned_download_url = AsyncMock(return_value="https://storage.example/owned")
    path = (
        "/api/service/files/v1/modes"
        if kind == "modes"
        else f"/api/service/files/v1/{uuid4()}/download"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
    assert (
        response.status_code
        == {"download": 307, "modes": 200, "missing": 404, "anonymous": 401}[kind]
    )
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["pragma"] == "no-cache"
    assert {"cookie", "authorization"} <= {
        value.strip().lower() for value in response.headers["vary"].split(",")
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [None, "document.pdf"])
async def test_storage_download_signed_response_cannot_be_cached(name):
    storage = MinioFileStorage.__new__(MinioFileStorage)
    storage._client = Mock()
    storage._client.presigned_get_object.return_value = "https://storage.example/owned"
    storage._bucket = "fixture"
    storage._presign_expiry = 3600
    storage._public_endpoint = ""
    await storage.get_presigned_url(file_key="PRIVATE_KEY", download_name=name)
    headers = storage._client.presigned_get_object.call_args.kwargs["response_headers"]
    assert headers["response-cache-control"] == "private, no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("vary", ["Accept-Encoding, Cookie", "*"])
async def test_private_policy_preserves_existing_vary_and_authentication_headers(vary):
    app = FastAPI()
    setup_exception_handlers(app)
    app.router.route_class = PrivateFileRoute

    @app.get("/success")
    async def success():
        return Response(headers={"Vary": vary})

    @app.get("/denied")
    async def denied():
        raise HTTPException(401, "Denied", headers={"WWW-Authenticate": "Bearer", "Vary": vary})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/success", "/denied"):
            response = await client.get(path)
            assert response.headers["cache-control"] == "private, no-store"
            values = response.headers["vary"].split(", ")
            assert len(values) == len(set(values))
            assert values == (
                ["*"] if vary == "*" else ["Accept-Encoding", "Cookie", "Authorization"]
            )
            if path == "/denied":
                assert response.status_code == 401
                assert response.headers["www-authenticate"] == "Bearer"
