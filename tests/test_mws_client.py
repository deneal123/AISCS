import types

import pytest

from service.domain.client.providers import mws
from service.settings import config


class _FakeModel:
    def __init__(self, model_id: str):
        self.id = model_id


class _FakeModelsAPI:
    def __init__(self, data):
        self._data = data
        self.calls = 0

    async def list(self):
        self.calls += 1
        return types.SimpleNamespace(data=self._data)


class _FakeClient:
    def __init__(self, data):
        self.models = _FakeModelsAPI(data)


class _BrokenModelsAPI:
    async def list(self):
        raise RuntimeError("upstream unavailable")


class _BrokenClient:
    def __init__(self):
        self.models = _BrokenModelsAPI()


@pytest.mark.asyncio
async def test_list_available_models_cached_between_calls():
    mws.clear_models_cache()

    fake_client = _FakeClient(
        [
            _FakeModel("gpt-4o"),
            _FakeModel("gpt-4o-mini"),
            _FakeModel("gpt-4o"),
            _FakeModel(""),
        ]
    )

    first = await mws.list_available_models(client=fake_client, force_refresh=True)
    second = await mws.list_available_models(client=fake_client)

    assert first == ["gpt-4o", "gpt-4o-mini"]
    assert second == ["gpt-4o", "gpt-4o-mini"]
    assert fake_client.models.calls == 1


@pytest.mark.asyncio
async def test_list_available_models_accepts_dict_items():
    mws.clear_models_cache()

    fake_client = _FakeClient(
        [
            {"id": "mws-gpt-alpha"},
            {"id": "kodify-2.0"},
            {"id": "kodify-2.0"},
            {"other": "ignored"},
        ]
    )

    data = await mws.list_available_models(client=fake_client, force_refresh=True)
    assert data == ["kodify-2.0", "mws-gpt-alpha"]


@pytest.mark.asyncio
async def test_list_available_models_returns_stale_cache_on_error():
    mws.clear_models_cache()

    seed_client = _FakeClient([_FakeModel("gpt-4.1"), _FakeModel("gpt-4.1-mini")])
    seeded = await mws.list_available_models(client=seed_client, force_refresh=True)

    broken_client = _BrokenClient()
    fallback = await mws.list_available_models(client=broken_client, force_refresh=True)

    assert seeded == ["gpt-4.1", "gpt-4.1-mini"]
    assert fallback == seeded


# --------------------------------------------------------------------------- #
# Нормализация базового URL                                                     #
# --------------------------------------------------------------------------- #
# ⚠️ Проверяется РЕЗУЛЬТАТ через спеку провайдера, а не приватный
# `_resolve_mws_base_url`: обвязка переехала в общую фабрику, и тест, привязанный к
# имени хелпера, ловил бы переезд, а не поведение.
@pytest.mark.parametrize(
    ("configured", "expected", "why"),
    [
        ("https://api.gpt.mws.ru", "https://api.gpt.mws.ru/v1", "суффикс дописывается"),
        ("https://api.gpt.mws.ru/v1", "https://api.gpt.mws.ru/v1", "и не задваивается"),
        ("https://api.gpt.mws.ru/", "https://api.gpt.mws.ru/v1", "хвостовой слэш срезается"),
        ("", "https://api.gpt.mws.ru/v1", "пусто → дефолт провайдера"),
    ],
)
def test_base_url_normalization(monkeypatch, configured, expected, why):
    from service.domain.client.providers.runtime import ProviderRuntime

    monkeypatch.setattr(config.agents, "mws_base_url", configured)
    monkeypatch.setattr(config.agents, "openai_base_url", "")

    assert ProviderRuntime(mws.SPEC).resolve_base_url() == expected, why


def test_base_url_falls_back_to_legacy_openai_naming(monkeypatch):
    """⚠️ Наследие: базу MWS можно задать и через `openai_base_url`.

    Второй источник существует ради старых env-файлов; потеряв его, мы молча увели бы
    таких пользователей на дефолтный адрес.
    """
    from service.domain.client.providers.runtime import ProviderRuntime

    monkeypatch.setattr(config.agents, "mws_base_url", "")
    monkeypatch.setattr(config.agents, "openai_base_url", "https://legacy.example")

    assert ProviderRuntime(mws.SPEC).resolve_base_url() == "https://legacy.example/v1"
