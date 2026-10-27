"""An upload must not bind a repository graph to another owner's conversation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from service.composition.state import (
    get_billing_service,
    get_chat_application_service,
    get_optional_redis_client,
)
from service.models.auth_models import AuthProfile
from service.models.key_value import UserTypes
from service.services.chat.application.chat_application_service import ChatApplicationService
from service.services.chat.presentation.http import upload_api
from service.shared.security.auth_checker import check_auth


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["foreign", "owned", "new", "unbound", "unavailable"])
async def test_thread_ownership_checked_before_processing_or_charging(monkeypatch, case):
    requester, owner, thread = uuid4(), uuid4(), uuid4()
    owner = owner if case == "foreign" else requester if case == "owned" else None
    thread_id = "" if case == "unbound" else str(thread)
    persistence = SimpleNamespace(
        get_thread_owner=AsyncMock(
            return_value=owner,
            side_effect=OSError("PRIVATE_OWNER_LOOKUP_BODY") if case == "unavailable" else None,
        )
    )
    service = ChatApplicationService(
        chat_service=SimpleNamespace(persistence_service=persistence), file_service=object()
    )
    execute = AsyncMock(
        return_value={
            "filename": "fixture.zip",
            "file_type": "repository",
            "size": 7,
            "extracted_text": "fixture",
            "thread_id": str(thread),
            "file_id": str(uuid4()),
            "content_sha256": "a" * 64,
            "mime_type": "application/zip",
            "file_url": "owned",
            "file_key": "owned",
            "temp_file": False,
            "repo_graph_id": "fixture-graph",
        }
    )
    monkeypatch.setattr(
        upload_api, "get_upload_use_case", lambda _: SimpleNamespace(execute=execute)
    )
    monkeypatch.setattr(upload_api, "_affordable_transcription_sec", AsyncMock(return_value=None))
    monkeypatch.setattr(upload_api, "_schedule_graph_indexing", lambda *_: None)
    billing = SimpleNamespace(has_sufficient_credits=AsyncMock(return_value=True))
    redis = SimpleNamespace(lpush=AsyncMock(), ltrim=AsyncMock(), expire=AsyncMock())
    app = FastAPI()
    app.include_router(upload_api.upload_router, prefix="/api/chats")
    app.dependency_overrides[check_auth] = lambda: AuthProfile(
        user_id=requester, fingerprint=None, type=UserTypes.REGISTERED
    )
    app.dependency_overrides[get_chat_application_service] = lambda: service
    app.dependency_overrides[get_billing_service] = lambda: billing
    app.dependency_overrides[get_optional_redis_client] = lambda: redis
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://fixture"
    ) as client:
        response = await client.post(
            "/api/chats/upload",
            data={"thread_id": thread_id},
            files={"file": ("fixture.zip", b"fixture", "application/zip")},
        )
    if case == "unbound":
        persistence.get_thread_owner.assert_not_awaited()
    else:
        persistence.get_thread_owner.assert_awaited_once_with(thread_id)
    if case in {"foreign", "unavailable"}:
        assert response.status_code == (404 if case == "foreign" else 500)
        if case == "foreign":
            assert response.json() == {"detail": "Thread not found"}
        assert "PRIVATE_OWNER_LOOKUP_BODY" not in response.text
        billing.has_sufficient_credits.assert_not_awaited()
        execute.assert_not_awaited()
        redis.lpush.assert_not_awaited()
    else:
        assert response.status_code == 200
        billing.has_sufficient_credits.assert_awaited_once()
        execute.assert_awaited_once()
        assert redis.lpush.await_count == (0 if case == "unbound" else 1)
        assert redis.ltrim.await_count == redis.lpush.await_count
        assert redis.expire.await_count == redis.lpush.await_count
