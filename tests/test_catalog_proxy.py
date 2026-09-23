"""Каталог моделей ходит через прокси — и обе реализации прокси не расходятся.

⚠️ ЗАЧЕМ. openrouter.ai заблокирован в РФ: без прокси запрос за каталогом падает, каталог
остаётся пустым, а пустой каталог снимает инструменты со ВСЕХ моделей и роняет окно
контекста к дефолту. Молча — читается это через `.get()` с фолбэком.

⚠️ `model_catalog.catalog_proxy_url` НАМЕРЕННО дублирует `_http.build_proxy_url`: файл
каталога обязан быть самодостаточным, иначе его побайтовая сверка с копией backend
неисполнима (ровно так дефект и появился). Раз дублирование осознанное — расхождение
двух реализаций стережёт тест, а не надежда.
"""

from __future__ import annotations

import httpx
import pytest

from service.domain.client.providers import _http
from service.shared import model_catalog


@pytest.fixture
def proxy_settings(monkeypatch):
    from service.settings import config

    monkeypatch.setattr(config.agents, "proxy_providers", "openrouter,openai")
    monkeypatch.setattr(config.agents, "proxy_host", "proxy.example")
    monkeypatch.setattr(config.agents, "proxy_port", 3128)
    monkeypatch.setattr(config.agents, "proxy_user", "")
    monkeypatch.setattr(config.agents, "proxy_pass", "")
    return monkeypatch


# --------------------------------------------------------------------------- #
# Две реализации обязаны давать один ответ                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("providers", "host", "port", "user", "password"),
    [
        ("openrouter,openai", "proxy.example", 3128, "", ""),
        ("openrouter", "proxy.example", 3128, "u", "p"),
        ("OpenRouter", "proxy.example", 3128, "", ""),
        ("  openrouter  ", "proxy.example", 3128, "", ""),
        ("routerai,gigachat", "proxy.example", 3128, "", ""),
        ("", "proxy.example", 3128, "", ""),
        ("openrouter", "", 3128, "", ""),
        ("openrouter", "proxy.example", None, "", ""),
    ],
)
def test_catalog_proxy_agrees_with_provider_proxy(
    monkeypatch, providers, host, port, user, password
):
    from service.settings import config

    monkeypatch.setattr(config.agents, "proxy_providers", providers)
    monkeypatch.setattr(config.agents, "proxy_host", host)
    monkeypatch.setattr(config.agents, "proxy_port", port)
    monkeypatch.setattr(config.agents, "proxy_user", user)
    monkeypatch.setattr(config.agents, "proxy_pass", password)

    assert model_catalog.catalog_proxy_url() == _http.build_proxy_url("openrouter")


# --------------------------------------------------------------------------- #
# Прокси доезжает до httpx-клиента                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_fetch_goes_through_the_proxy(proxy_settings, monkeypatch):
    seen: dict = {}

    class _Client:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url):
            return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    await model_catalog._fetch_openrouter()

    assert seen.get("proxy") == "http://proxy.example:3128"


@pytest.mark.asyncio
async def test_no_proxy_configured_means_direct_client(monkeypatch):
    """Пустой прокси не должен превращаться в `proxy=""` — httpx такой URL не примет."""
    from service.settings import config

    monkeypatch.setattr(config.agents, "proxy_providers", "")
    seen: dict = {}

    class _Client:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url):
            return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    await model_catalog._fetch_openrouter()

    assert "proxy" not in seen
