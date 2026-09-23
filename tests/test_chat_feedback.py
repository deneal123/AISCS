import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from service.composition.state import get_chat_application_service, get_optional_redis_client
from service.main import app
from service.models.auth_models import AuthProfile
from service.models.key_value import UserTypes
from service.services.chat.infrastructure.feedback_store import feedback_key
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

    async def hdel(self, key, field):
        self.store.get(key, {}).pop(field, None)

    async def hgetall(self, key):
        return self.store.get(key, {})


def test_feedback_key_is_stable_and_trims():
    # Значения зафиксированы и совпадают с фронтовым feedbackKey.js (проверено).
    assert feedback_key("test") == "afd071e5"
    assert feedback_key("  test  ") == "afd071e5"
    assert feedback_key("ab") == "4d2505ca"


@pytest.mark.asyncio
async def test_set_feedback_stores_rating():
    class _FakeSvc:
        async def ensure_thread_owner(self, thread_id, requester_id=None):
            return None

    fake_redis = _FakeRedis()
    app.dependency_overrides[get_chat_application_service] = lambda: _FakeSvc()
    app.dependency_overrides[get_optional_redis_client] = lambda: fake_redis
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/api/chats/T1/feedback", json={"content_key": "k1", "rating": "up"})
        assert r.status_code == 204
        assert fake_redis.store["chat:fb:T1"]["k1"] == "up"

        # Снятие оценки (rating=None) удаляет ключ.
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r2 = await ac.post("/api/chats/T1/feedback", json={"content_key": "k1", "rating": None})
        assert r2.status_code == 204
        assert "k1" not in fake_redis.store.get("chat:fb:T1", {})
    finally:
        app.dependency_overrides.pop(get_chat_application_service, None)
        app.dependency_overrides.pop(get_optional_redis_client, None)


@pytest.mark.asyncio
async def test_history_merges_feedback_by_content_key():
    class _FakeSvc:
        async def get_thread_messages(self, thread_id, page, per_page, requester_id):
            return {"thread_id": thread_id, "messages": [{"sender": "agent", "content": "Ответ"}]}

    fake_redis = _FakeRedis()
    fake_redis.store["chat:fb:T1"] = {feedback_key("Ответ"): "up"}
    app.dependency_overrides[get_chat_application_service] = lambda: _FakeSvc()
    app.dependency_overrides[get_optional_redis_client] = lambda: fake_redis
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/api/chats/T1")
        assert r.status_code == 200
        assert r.json()["messages"][0]["feedback"] == "up"
    finally:
        app.dependency_overrides.pop(get_chat_application_service, None)
        app.dependency_overrides.pop(get_optional_redis_client, None)
