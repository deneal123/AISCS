"""Прокси доезжает до HTTP-клиента провайдера.

⚠️ ЗАЧЕМ. Прокси — это то, чем зарубежные провайдеры (OpenRouter, OpenAI) вообще
достижимы из РФ. Перестань он применяться — и они просто «не отвечают», причём код при
этом выглядит исправным: клиент создан, запрос ушёл, соединения нет. Ни исключения в
конфигурации, ни строчки в логе.

При этом ни `_http.build_proxy_url`, ни его три места применения не были покрыты ничем.
Проверка появилась перед сменой `proxies=` на `proxy=` (первый параметр удалён в
httpx 0.28): менять то, что не проверяется, — это и есть тихая поломка.

⚠️ Per-provider allowlist — не украшение. Российские провайдеры через зарубежный прокси
НЕ достаются, поэтому список задаётся явно, а не «всем подряд».
"""

from __future__ import annotations

import certifi
import httpx
import pytest

from service.domain.client.providers import _http, openai_compatible


@pytest.fixture
def proxy_settings(monkeypatch):
    """Прокси сконфигурирован и разрешён для acme."""
    from service.settings import config

    monkeypatch.setattr(config.agents, "proxy_providers", "acme")
    monkeypatch.setattr(config.agents, "proxy_host", "proxy.example")
    monkeypatch.setattr(config.agents, "proxy_port", 3128)
    monkeypatch.setattr(config.agents, "proxy_user", "")
    monkeypatch.setattr(config.agents, "proxy_pass", "")
    return monkeypatch


# --------------------------------------------------------------------------- #
# build_proxy_url                                                               #
# --------------------------------------------------------------------------- #
def test_proxy_url_for_allowed_provider(proxy_settings):
    assert _http.build_proxy_url("acme") == "http://proxy.example:3128"


def test_provider_outside_the_allowlist_gets_nothing(proxy_settings):
    """⚠️ Российские провайдеры через зарубежный прокси НЕ достаются.

    Раздать прокси всем — значит выключить routerai/gigachat/mws.
    """
    assert _http.build_proxy_url("routerai") == ""


@pytest.mark.parametrize("name", ["ACME", "  acme  ", "Acme"])
def test_allowlist_matching_is_forgiving(proxy_settings, name):
    """Регистр и пробелы в CSV не должны выключать прокси."""
    assert _http.build_proxy_url(name) == "http://proxy.example:3128"


def test_credentials_are_embedded_when_given(proxy_settings):
    from service.settings import config

    proxy_settings.setattr(config.agents, "proxy_user", "u")
    proxy_settings.setattr(config.agents, "proxy_pass", "p")

    assert _http.build_proxy_url("acme") == "http://u:p@proxy.example:3128"


@pytest.mark.parametrize(
    ("field", "value", "why"),
    [
        ("proxy_host", "", "нет хоста"),
        ("proxy_port", 0, "нет порта"),
        ("proxy_providers", "", "пустой allowlist"),
    ],
)
def test_incomplete_config_disables_proxy(proxy_settings, field, value, why):
    """Недонастроенный прокси — это ПРЯМОЕ соединение, а не битый URL."""
    from service.settings import config

    proxy_settings.setattr(config.agents, field, value)

    assert _http.build_proxy_url("acme") == "", why


# --------------------------------------------------------------------------- #
# Прокси доезжает до клиента                                                    #
# --------------------------------------------------------------------------- #
def _captured_kwargs(monkeypatch) -> dict:
    """Перехватить kwargs, с которыми собирают httpx.AsyncClient."""
    seen: dict = {}
    real = httpx.AsyncClient

    class _Spy(real):
        def __init__(self, **kw):
            seen.update(kw)
            super().__init__(**kw)

    monkeypatch.setattr(httpx, "AsyncClient", _Spy)
    return seen


def test_openai_compatible_client_gets_the_proxy(proxy_settings):
    """Общий путь четырёх провайдеров."""
    seen = _captured_kwargs(proxy_settings)

    openai_compatible.make_http_client("acme", timeout=5.0)

    assert seen.get("proxy") == "http://proxy.example:3128", (
        "прокси не доехал до клиента — зарубежные провайдеры станут недостижимы"
    )
    assert "proxies" not in seen, "`proxies` УДАЛЁН в httpx 0.28 — возврат к нему сломает прокси"


def test_openai_compatible_client_without_proxy_passes_none(proxy_settings):
    """⚠️ Обратная сторона: провайдеру вне списка прокси НЕ навязывается.

    Без этой проверки «починку» можно было бы сделать, выставив прокси всем, и тест выше
    остался бы зелёным — а российские провайдеры отвалились бы.
    """
    seen = _captured_kwargs(proxy_settings)

    openai_compatible.make_http_client("routerai", timeout=5.0)

    assert not seen.get("proxy") and not seen.get("proxies")


def test_gigachat_client_gets_the_proxy(proxy_settings):
    """У GigaChat свой HTTP-клиент — прокси собирается отдельным кодом."""
    from service.domain.client.providers import gigachat
    from service.settings import config

    proxy_settings.setattr(config.agents, "proxy_providers", "gigachat")
    proxy_settings.setattr(config.agents, "gigachat_ca_bundle", certifi.where())
    proxy_settings.setattr(config.agents, "gigachat_verify_ssl", True)
    gigachat._reset_token_manager()
    seen = _captured_kwargs(proxy_settings)

    gigachat._make_http_client()

    assert seen.get("proxy"), "прокси не доехал до клиента GigaChat"
    assert "proxies" not in seen, "`proxies` УДАЛЁН в httpx 0.28"


@pytest.mark.asyncio
async def test_gigachat_oauth_request_gets_the_proxy(proxy_settings):
    """⚠️ И OAuth-запрос тоже: токен берётся ДО основного клиента.

    Прокси, применённый только к чат-клиенту, оставил бы недостижимым сам вход — то есть
    провайдер не работал бы вовсе, а выглядело бы как «неверный ключ».
    """
    from service.domain.client.providers.gigachat_auth import GigaChatTokenManager

    seen = _captured_kwargs(proxy_settings)
    manager = GigaChatTokenManager(
        authorization_key="k",
        scope="S",
        oauth_url="https://oauth.invalid",
        verify=False,
        timeout=1.0,
        skew_sec=0,
        proxy_url="http://proxy.example:3128",
    )
    with pytest.raises(Exception):  # noqa: B017 — сеть недоступна, важен факт сборки клиента
        await manager.get_token()

    assert seen.get("proxy"), "OAuth-запрос пошёл мимо прокси"
    assert "proxies" not in seen, "`proxies` УДАЛЁН в httpx 0.28"


# --------------------------------------------------------------------------- #
# Каталог OpenRouter — тот же прокси, что у клиентов                            #
# --------------------------------------------------------------------------- #
def _spy_with_mock(monkeypatch) -> dict:
    """Как `_captured_kwargs`, но клиент собирается с MockTransport: `.get()` не ходит в
    сеть (мгновенный пустой каталог), а перехваченные kwargs остаются проверяемыми."""
    seen: dict = {}
    real = httpx.AsyncClient

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    class _Spy(real):
        def __init__(self, **kw):
            seen.update(kw)
            kw.pop("proxy", None)  # MockTransport и proxy вместе httpx не собирает
            super().__init__(transport=httpx.MockTransport(_handler), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", _Spy)
    return seen


@pytest.mark.asyncio
async def test_openrouter_catalog_fetch_goes_through_proxy(proxy_settings):
    """СУТЬ 2.2: каталог моделей OpenRouter тянется ЧЕРЕЗ прокси, как и его клиенты.

    Тянулся голым httpx мимо прокси: в dev (прокси не задан) незаметно, а в проде с
    прокси запрос падал → каталог пуст → инструменты сняты со всех моделей, окно
    контекста дефолтное, компрессор впустую. Тихо, потому что `except → {}`.
    """
    from service.settings import config
    from service.shared import model_catalog

    proxy_settings.setattr(config.agents, "proxy_providers", "openrouter")
    seen = _spy_with_mock(proxy_settings)

    await model_catalog._fetch_openrouter()

    assert seen.get("proxy") == "http://proxy.example:3128", (
        "каталог OpenRouter пошёл мимо прокси — в проде он будет вечно пуст"
    )
    assert "proxies" not in seen, "`proxies` УДАЛЁН в httpx 0.28"


@pytest.mark.asyncio
async def test_openrouter_catalog_fetch_direct_when_proxy_unconfigured(proxy_settings):
    """Обратная сторона: без настроенного прокси (как в dev) — ПРЯМОЕ соединение.

    Без этой проверки «починку» можно было бы сделать, навязав прокси всегда, и dev, где
    openrouter.ai достижим напрямую, сломался бы (пустой каталог там, где он работал).
    """
    from service.settings import config
    from service.shared import model_catalog

    proxy_settings.setattr(config.agents, "proxy_providers", "openrouter")
    proxy_settings.setattr(config.agents, "proxy_host", "")  # прокси не сконфигурирован
    seen = _spy_with_mock(proxy_settings)

    await model_catalog._fetch_openrouter()

    assert not seen.get("proxy"), "без прокси-конфига каталог должен идти напрямую (dev)"
