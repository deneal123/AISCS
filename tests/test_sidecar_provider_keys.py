"""Доставка провайдерских ключей в сайдкар (Фаза 3).

Зачем. Ключи, заменённые админом, лежат в БД backend'а, а после флипа LLM-вызовы делает
САЙДКАР — у которого ни PG, ни Redis. До этого механизма смена ключа до него НЕ доезжала:
ре-гидрация в воркере чинила клиент, которым уже никто не звонит, а сайдкар молча
продолжал бить старым ключом из env. Симптом для админа — «заменил мёртвый ключ, ничего
не починилось».

Свойства, которые тут закрепляются:
* в http-режиме снимок доезжает, и в заголовке есть ключ шлюза (иначе любой в внутренней
  сети подменял бы ключи провайдеров);
* версии совпали → НЕ пушим (секреты не гоняем по сети зря);
* in-process → не ходим вовсе;
* сайдкар недоступен → не роняем вызов, но и не молчим.
"""

import json
from types import SimpleNamespace

import httpx
import pytest

from service.infrastructure.agents_client import sidecar_providers
from service.infrastructure.agents_client.sidecar_providers import (
    fetch_keys_version,
    push_provider_keys,
)


def _cfg(url: str = "http://agents:8090", gateway_key: str = "gw-secret-key"):
    return SimpleNamespace(agents=SimpleNamespace(sidecar_url=url, llm_gateway_api_key=gateway_key))


class _Resp:
    """Совместимость с прежними вызовами `_patch(resp=_Resp(...))`."""

    def __init__(self, status: int, payload=None):
        self.status_code = status
        self.payload = payload if payload is not None else {}


def _patch(monkeypatch, *, resp=None, boom=None):
    """Подменяет ТРАНСПОРТ клиента, а не сам клиент.

    ⚠️ Раньше тест патчил `sidecar_providers.httpx.AsyncClient`. После перехода на общую
    базу такого атрибута нет: подмена молча перестала бы что-либо значить, а тест остался
    бы зелёным. Через `httpx.MockTransport` проверяется рабочий путь клиента целиком.

    ⚠️ И ключ в `_cfg` теперь ASCII: заголовки HTTP кодируются latin-1, и настоящий httpx
    на кириллице падает. Самодельный дублёр заголовки не кодировал вовсе и это прятал.
    """
    seen: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url).split("?")[0]
        seen["headers"] = dict(request.headers)
        seen["json"] = json.loads(request.content.decode("utf-8")) if request.content else None
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
async def test_push_sends_snapshot_with_gateway_auth(monkeypatch) -> None:
    seen = _patch(monkeypatch, resp=_Resp(200, {"applied": ["openai"], "version": 7}))

    ok = await push_provider_keys(_cfg(), version=7, overrides={"openai": "sk-новый"})

    assert ok is True
    assert seen["url"] == "http://agents:8090/providers/keys"
    assert seen["json"] == {"version": 7, "overrides": {"openai": "sk-новый"}}
    # Без заголовка эндпоинт открыт любому, кто дотянулся до внутренней сети.
    # ⚠️ Имя заголовка в нижнем регистре — httpx нормализует, самодельный дублёр нет.
    assert seen["headers"]["authorization"] == "Bearer gw-secret-key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs", [{"boom": "сеть легла"}, {"resp": _Resp(401)}, {"resp": _Resp(503)}]
)
async def test_push_failure_reports_false(monkeypatch, kwargs) -> None:
    """Не доставили — честный False; вызывающий залогирует деградацию, а не «всё ок»."""
    _patch(monkeypatch, **kwargs)
    assert await push_provider_keys(_cfg(), version=1, overrides={"openai": "sk-x"}) is False


@pytest.mark.asyncio
async def test_push_without_sidecar_url_does_nothing() -> None:
    assert await push_provider_keys(_cfg(url=""), version=1, overrides={}) is False


@pytest.mark.asyncio
async def test_fetch_version_reads_health(monkeypatch) -> None:
    seen = _patch(monkeypatch, resp=_Resp(200, {"provider_keys": {"version": 42}}))
    assert await fetch_keys_version(_cfg()) == 42
    assert seen["url"] == "http://agents:8090/health"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{}, {"provider_keys": {}}, {"provider_keys": {"version": "не число"}}]
)
async def test_fetch_version_tolerates_old_or_broken_sidecar(monkeypatch, payload) -> None:
    """Сайдкар старее backend'а версии не отдаёт — это не повод падать."""
    _patch(monkeypatch, resp=_Resp(200, payload))
    assert await fetch_keys_version(_cfg()) is None


@pytest.mark.asyncio
async def test_ensure_skips_push_when_versions_match(monkeypatch) -> None:
    """Секреты по сети зря не гоняем: версия сошлась — выходим до сборки снимка."""
    from service.services.admin.application.provider_key_service import ProviderKeyService

    monkeypatch.setattr(
        "service.infrastructure.agents_client.engine_factory.uses_http_engine", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "service.infrastructure.agents_client.sidecar_providers.fetch_keys_version",
        _async(5),
    )

    async def _must_not_push(*a, **k):
        raise AssertionError("версии совпали — пушить нечего")

    monkeypatch.setattr(
        "service.infrastructure.agents_client.sidecar_providers.push_provider_keys", _must_not_push
    )
    svc = ProviderKeyService.__new__(ProviderKeyService)
    assert await svc.ensure_sidecar_keys(5) is False


@pytest.mark.asyncio
async def test_ensure_is_noop_in_inprocess_mode(monkeypatch) -> None:
    from service.services.admin.application.provider_key_service import ProviderKeyService

    monkeypatch.setattr(
        "service.infrastructure.agents_client.engine_factory.uses_http_engine",
        lambda *a, **k: False,
    )

    async def _must_not_call(*a, **k):
        raise AssertionError("в in-process режиме сайдкар не трогаем")

    monkeypatch.setattr(
        "service.infrastructure.agents_client.sidecar_providers.fetch_keys_version", _must_not_call
    )
    svc = ProviderKeyService.__new__(ProviderKeyService)
    assert await svc.ensure_sidecar_keys(1) is False


@pytest.mark.asyncio
async def test_ensure_pushes_decrypted_overrides_on_version_drift(monkeypatch) -> None:
    """Расхождение версий (в т.ч. после рестарта сайдкара) → пушим полный снимок."""
    from service.services.admin.application.provider_key_service import ProviderKeyService

    monkeypatch.setattr(
        "service.infrastructure.agents_client.engine_factory.uses_http_engine", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "service.infrastructure.agents_client.sidecar_providers.fetch_keys_version", _async(-1)
    )
    monkeypatch.setattr(
        "service.services.admin.application.provider_key_service.decrypt_secret",
        lambda enc: f"расшифрован:{enc}",
    )
    pushed: dict = {}

    async def _capture(config, *, version, overrides):
        pushed.update(version=version, overrides=overrides)
        return True

    monkeypatch.setattr(
        "service.infrastructure.agents_client.sidecar_providers.push_provider_keys", _capture
    )

    svc = ProviderKeyService.__new__(ProviderKeyService)
    monkeypatch.setattr(svc, "_safe_get_all", _async({"openai": {"secret_enc": "ЗАШИФР"}}))

    assert await svc.ensure_sidecar_keys(9) is True
    assert pushed["version"] == 9
    assert pushed["overrides"] == {"openai": "расшифрован:ЗАШИФР"}


def _async(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner
