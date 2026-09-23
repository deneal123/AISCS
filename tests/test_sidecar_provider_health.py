"""Откуда админ-панель берёт здоровье провайдеров: сайдкар vs локальная проба.

После флипа ``AGENTS__ENGINE_MODE=http`` провайдерам звонит САЙДКАР, значит и мерить
надо оттуда: локальная проба backend'а отвечает на другой вопрос («доступен ли провайдер
ИЗ backend»), а его circuit_breaker после переезда трафика пуст.

Два свойства, ради которых тесты и написаны:
* в http-режиме данные берутся с сайдкара — иначе админ смотрел бы не туда и, например,
  «чинил» бы живого провайдера или считал мёртвого рабочим;
* сайдкар недоступен → честное «не знаем» (``unavailable``), а НЕ пустая таблица:
  пустую админ прочитает как «все провайдеры мертвы» и пойдёт чинить исправное.
"""

from types import SimpleNamespace

import httpx
import pytest

from service.infrastructure.agents_client import sidecar_providers
from service.infrastructure.agents_client.sidecar_providers import fetch_provider_health


def _cfg(url: str = "http://agents:8090", key: str = "test-key"):
    return SimpleNamespace(agents=SimpleNamespace(sidecar_url=url, llm_gateway_api_key=key))


class _Resp:
    """Совместимость с прежними вызовами `_patch_client(resp=_Resp(...))`."""

    def __init__(self, status: int, payload=None):
        self.status_code = status
        self.payload = payload if payload is not None else {}


def _patch_client(monkeypatch, *, resp=None, boom=None):
    """Подменяет ТРАНСПОРТ клиента, а не сам клиент.

    ⚠️ Раньше тест патчил `sidecar_providers.httpx.AsyncClient` — то есть знал, что
    модуль ходит в сеть сам. После перехода на общую базу такого атрибута нет: подмена
    молча перестала бы что-либо значить, а тест остался бы зелёным, ничего не проверяя.
    Через `httpx.MockTransport` проверяется РАБОЧИЙ путь клиента целиком — заголовки,
    разбор единой формы ошибки, классификация отказа.
    """
    seen: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url).split("?")[0]
        seen["params"] = dict(request.url.params)
        seen["headers"] = dict(request.headers)
        if boom is not None:
            raise httpx.ConnectError(str(boom))
        return httpx.Response(resp.status_code, json=resp.payload)

    transport = httpx.MockTransport(_handler)
    original = sidecar_providers._client

    def _factory(config, timeout):
        client = original(config, timeout)
        client._transport = transport
        return client

    monkeypatch.setattr(sidecar_providers, "_client", _factory)
    return seen


@pytest.mark.asyncio
async def test_returns_sidecar_payload(monkeypatch) -> None:
    payload = {"active_provider": "gigachat", "providers": {"mws": {"reachable": False}}}
    seen = _patch_client(monkeypatch, resp=_Resp(200, payload))

    assert await fetch_provider_health(_cfg(), force_probe=False) == payload
    assert seen["url"] == "http://agents:8090/providers/health"
    assert seen["params"] == {"force": "false"}


@pytest.mark.asyncio
async def test_force_probe_reaches_the_sidecar(monkeypatch) -> None:
    """Кнопка «Проверить» обязана долететь: иначе админ жмёт её, а данные из breaker'а."""
    seen = _patch_client(monkeypatch, resp=_Resp(200, {"providers": {}}))
    await fetch_provider_health(_cfg(), force_probe=True)
    assert seen["params"] == {"force": "true"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"boom": "сеть легла"},
        {"resp": _Resp(503, {"error": "engine unavailable"})},
        {"resp": _Resp(200, {"providers": "не словарь"})},  # мусор вместо таблицы
        {"resp": _Resp(200, ["совсем не то"])},  # не словарь вовсе
    ],
)
async def test_failures_degrade_to_none_not_to_empty_table(monkeypatch, kwargs) -> None:
    """None = «считай локально». Вернуть пустое — значит нарисовать «всё сломано»."""
    _patch_client(monkeypatch, **kwargs)
    assert await fetch_provider_health(_cfg()) is None


@pytest.mark.asyncio
async def test_no_sidecar_url_means_no_call() -> None:
    assert await fetch_provider_health(_cfg(url="")) is None


@pytest.mark.asyncio
async def test_admin_prefers_sidecar_in_http_mode(monkeypatch) -> None:
    """Главное свойство шва: в http-режиме панель показывает данные САЙДКАРА."""
    from service.services.admin.application.admin_service import AdminService

    monkeypatch.setattr(
        "service.infrastructure.agents_client.engine_factory.uses_http_engine",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        "service.infrastructure.agents_client.sidecar_providers.fetch_provider_health",
        _async_return({"active_provider": "sidecar-said-this", "providers": {}}),
    )
    svc = AdminService.__new__(AdminService)
    data = await svc._compute_provider_health()
    assert data["active_provider"] == "sidecar-said-this"


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


@pytest.mark.asyncio
async def test_admin_reports_unavailable_when_sidecar_is_silent(monkeypatch) -> None:
    """Локальной пробы больше нет. Пустая таблица солгала бы: админ прочитал бы её как
    «все провайдеры мертвы». Отдаём явный признак «не знаем»."""
    from service.services.admin.application.admin_service import AdminService

    monkeypatch.setattr(
        "service.infrastructure.agents_client.sidecar_providers.fetch_provider_health",
        _async_return(None),
    )
    data = await AdminService.__new__(AdminService)._compute_provider_health()

    assert data["unavailable"] is True
    assert data["providers"] == {}


@pytest.mark.asyncio
async def test_health_request_carries_bearer_key(monkeypatch) -> None:
    """`/providers/health` теперь ЗАКРЫТ ключом — заголовок обязан уходить.

    ⚠️ Половина пары: сайдкар требует ключ (agents/tests/test_internal_auth.py), backend
    его шлёт. Раньше ключ уходил только на `/providers/keys`, а три GET-ручки звались
    без него и работали лишь потому, что сайдкар их не проверял.
    """
    seen = _patch_client(monkeypatch, resp=_Resp(200, {"providers": {}}))

    await fetch_provider_health(_cfg(), force_probe=False)

    # ⚠️ Имя в нижнем регистре: httpx нормализует заголовки, а самодельный дублёр
    # этого не делал. Настоящий транспорт вскрывает такие расхождения.
    assert seen["headers"]["authorization"] == "Bearer test-key"
