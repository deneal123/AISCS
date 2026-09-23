import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from service.composition.state import get_chat_application_service
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
async def test_list_threads_returns_threads():
    class _FakeSvc:
        async def list_threads(self, requester_id, page, per_page):
            return {
                "page": page,
                "per_page": per_page,
                "threads": [
                    {
                        "thread_id": "T1",
                        "title": "Hello",
                        "created_at": "2025-01-01T00:00:00Z",
                        "updated_at": None,
                    }
                ],
            }

    app.dependency_overrides[get_chat_application_service] = lambda: _FakeSvc()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/api/chats/?page=1&per_page=10")

        assert r.status_code == 200
        data = r.json()
        assert data["threads"][0]["thread_id"] == "T1"
    finally:
        app.dependency_overrides.pop(get_chat_application_service, None)


@pytest.mark.asyncio
async def test_delete_thread_returns_404_when_not_found():
    class _FakeSvc:
        async def delete_thread(self, thread_id, requester_id=None):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Thread not found")

    app.dependency_overrides[get_chat_application_service] = lambda: _FakeSvc()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.delete("/api/chats/UNKNOWN")

        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_chat_application_service, None)


@pytest.mark.asyncio
async def test_delete_thread_returns_204_when_deleted():
    class _FakeSvc:
        async def delete_thread(self, thread_id, requester_id=None):
            return True

    app.dependency_overrides[get_chat_application_service] = lambda: _FakeSvc()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.delete("/api/chats/T1")

        assert r.status_code == 204
    finally:
        app.dependency_overrides.pop(get_chat_application_service, None)


@pytest.mark.asyncio
async def test_rename_thread_returns_updated_title():
    class _FakeSvc:
        async def rename_thread(self, thread_id, title, requester_id=None):
            return {"thread_id": thread_id, "title": title}

    app.dependency_overrides[get_chat_application_service] = lambda: _FakeSvc()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.patch("/api/chats/T1", json={"title": "Renamed"})

        assert r.status_code == 200
        data = r.json()
        assert data["thread_id"] == "T1"
        assert data["title"] == "Renamed"
    finally:
        app.dependency_overrides.pop(get_chat_application_service, None)


@pytest.mark.asyncio
async def test_rename_thread_returns_404_when_not_found():
    class _FakeSvc:
        async def rename_thread(self, thread_id, title, requester_id=None):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Thread not found")

    app.dependency_overrides[get_chat_application_service] = lambda: _FakeSvc()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.patch("/api/chats/UNKNOWN", json={"title": "X"})

        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_chat_application_service, None)
