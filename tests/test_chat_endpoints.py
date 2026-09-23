import uuid
from datetime import UTC

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport

from service.composition.state import get_chat_application_service, get_optional_redis_client
from service.main import app
from service.models.auth_models import AuthProfile
from service.models.key_value import UserTypes
from service.shared.security.auth_checker import check_auth

_TEST_USER_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def _override_check_auth():
    app.dependency_overrides[check_auth] = lambda: AuthProfile(
        user_id=_TEST_USER_ID, fingerprint="test", type=UserTypes.REGISTERED
    )
    try:
        yield
    finally:
        app.dependency_overrides.pop(check_auth, None)


@pytest.mark.asyncio
async def test_create_thread_persists():
    from datetime import datetime

    now = datetime.now(UTC)
    created = {"called": False}

    class _FakeSvc:
        async def create_thread(self, requester_id, title):
            created["called"] = True
            return {"thread_id": "t-123", "title": title, "created_at": now.isoformat()}

    app.dependency_overrides[get_chat_application_service] = lambda: _FakeSvc()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/chats/", json={"user_id": 123, "title": "My thread"})

        assert resp.status_code == 201
        assert created["called"] is True
        body = resp.json()
        assert (
            "created_at" in body
            and isinstance(body["created_at"], str)
            and body["created_at"] != ""
        )
    finally:
        app.dependency_overrides.pop(get_chat_application_service, None)


@pytest.mark.asyncio
async def test_get_thread_messages_returns_rows():
    class _FakeSvc:
        async def get_thread_messages(self, thread_id, page, per_page, requester_id=None):
            return {
                "thread_id": thread_id,
                "messages": [{"sender": "user", "content": "hello", "created_at": None}],
                "page": page,
                "per_page": per_page,
            }

    app.dependency_overrides[get_chat_application_service] = lambda: _FakeSvc()
    app.dependency_overrides[get_optional_redis_client] = lambda: None
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/chats/test-thread-id")

        assert resp.status_code == 200
        body = resp.json()
        assert body["thread_id"] == "test-thread-id"
        assert isinstance(body["messages"], list)
    finally:
        app.dependency_overrides.pop(get_chat_application_service, None)
        app.dependency_overrides.pop(get_optional_redis_client, None)
