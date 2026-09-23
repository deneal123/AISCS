import uuid

import pytest
from httpx import ASGITransport, AsyncClient

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


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def hset(self, key, field, value):
        self.store.setdefault(key, {})[field] = value

    async def hgetall(self, key):
        return self.store.get(key, {})


class _FakeSvc:
    async def ensure_thread_owner(self, thread_id, requester_id=None):
        return None


@pytest.mark.asyncio
async def test_save_and_get_trace_roundtrip():
    fake_redis = _FakeRedis()
    app.dependency_overrides[get_chat_application_service] = lambda: _FakeSvc()
    app.dependency_overrides[get_optional_redis_client] = lambda: fake_redis
    try:
        transport = ASGITransport(app=app)
        session = {
            "id": "s1",
            "title": "Вопрос",
            "status": "done",
            "events": [{"id": "e1", "kind": "done", "title": "Шаг"}],
        }
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.put("/api/chats/T1/trace", json={"content_key": "ck", "trace": session})
        assert r.status_code == 204

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r2 = await ac.get("/api/chats/T1/trace")
        assert r2.status_code == 200
        traces = r2.json()["traces"]
        assert traces["ck"]["status"] == "done"
        assert traces["ck"]["events"][0]["title"] == "Шаг"
    finally:
        app.dependency_overrides.pop(get_chat_application_service, None)
        app.dependency_overrides.pop(get_optional_redis_client, None)


@pytest.mark.asyncio
async def test_get_trace_empty_when_none():
    fake_redis = _FakeRedis()
    app.dependency_overrides[get_chat_application_service] = lambda: _FakeSvc()
    app.dependency_overrides[get_optional_redis_client] = lambda: fake_redis
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/api/chats/EMPTY/trace")
        assert r.status_code == 200
        assert r.json()["traces"] == {}
    finally:
        app.dependency_overrides.pop(get_chat_application_service, None)
        app.dependency_overrides.pop(get_optional_redis_client, None)
