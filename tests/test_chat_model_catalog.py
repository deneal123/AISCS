import uuid

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from service.composition.state import get_chat_application_service
from service.main import app
from service.models.auth_models import AuthProfile
from service.models.key_value import UserTypes
from service.services.chat.infrastructure import model_catalog as catalog_module
from service.services.chat.infrastructure.model_catalog import derive_capabilities
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


def test_derive_capabilities_from_modalities():
    assert derive_capabilities(
        {"input_modalities": ["text", "image"], "output_modalities": ["text"]}
    ) == ["vision"]
    assert "audio" in derive_capabilities({"input_modalities": ["text", "audio"]})
    assert "image_out" in derive_capabilities(
        {"input_modalities": ["text"], "output_modalities": ["image"]}
    )
    assert derive_capabilities(None) == []


@pytest.mark.asyncio
async def test_models_catalog_endpoint():
    class _FakeSvc:
        async def get_models_catalog(self):
            return [
                {
                    "id": "openai/gpt-4o",
                    "label": "GPT-4o",
                    "context_window": 128000,
                    "capabilities": ["vision"],
                }
            ]

    app.dependency_overrides[get_chat_application_service] = lambda: _FakeSvc()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/api/chats/models/catalog")
        assert r.status_code == 200
        m = r.json()["models"][0]
        assert m["id"] == "openai/gpt-4o"
        assert m["context_window"] == 128000
        assert "vision" in m["capabilities"]
    finally:
        app.dependency_overrides.pop(get_chat_application_service, None)


# --------------------------------------------------------------------------- #
# Прокси                                                                        #
# --------------------------------------------------------------------------- #
# ⚠️ ЗАЧЕМ. openrouter.ai заблокирован в РФ. Здесь каталог тянулся ГОЛЫМ httpx мимо
# прокси — в dev незаметно (там прокси не нужен), а в проде запрос падал, каталог
# оставался пуст, и tools снимались со ВСЕХ моделей вместе с окном контекста. Копия
# сайдкара прокси получила, эта — нет, и побайтовая сверка копий этого не поймала,
# потому что была неисполнима. Проверка держит именно ту сторону, что отставала.
class _FakeAsyncClient:
    seen: dict = {}

    def __init__(self, **kwargs):
        type(self).seen = dict(kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, url):
        return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))


@pytest.fixture
def _proxy_configured(monkeypatch):
    from service.settings import config

    monkeypatch.setattr(config.agents, "proxy_providers", "openrouter,openai")
    monkeypatch.setattr(config.agents, "proxy_host", "proxy.example")
    monkeypatch.setattr(config.agents, "proxy_port", 3128)
    monkeypatch.setattr(config.agents, "proxy_user", "")
    monkeypatch.setattr(config.agents, "proxy_pass", "")
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return monkeypatch


@pytest.mark.asyncio
async def test_catalog_fetch_goes_through_the_proxy(_proxy_configured):
    await catalog_module._fetch_openrouter()

    assert _FakeAsyncClient.seen.get("proxy") == "http://proxy.example:3128"


@pytest.mark.asyncio
async def test_catalog_fetch_is_direct_without_proxy(_proxy_configured):
    """Пустой прокси не превращается в `proxy=""` — httpx такой URL не примет."""
    from service.settings import config

    _proxy_configured.setattr(config.agents, "proxy_providers", "")

    await catalog_module._fetch_openrouter()

    assert "proxy" not in _FakeAsyncClient.seen
