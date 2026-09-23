"""Клиент backend к LLM-шлюзу сайдкара — и главное, сохранность usage.

Backend иногда сам зовёт LLM (аналитика памяти извлекает факты из переписки). Раньше он
ходил в мультипровайдерный слой напрямую; теперь — через шлюз сайдкара, потому что
провайдерами владеет он: ключи, политика, фейловер. Иначе у нас снова два мнения о том,
кто из провайдеров жив.

⚠️ Главное, что здесь закрепляется: **usage возвращается вместе с текстом**. Эти вызовы
ТАРИФИЦИРУЮТСЯ (извлечение фактов списывается с пользователя отдельно), а форма usage
сменилась с объекта SDK на словарь OpenAI-формата. Потеря токенов не падает — она просто
делает работу бесплатной, и заметить это нечем.
"""

import json
from types import SimpleNamespace

import httpx
import pytest

import service.infrastructure.llm_gateway as llm_gateway_mod
from service.infrastructure.llm_gateway import chat_completion


def _cfg(url: str = "http://agents:8090"):
    return SimpleNamespace(
        agents=SimpleNamespace(sidecar_url=url, llm_gateway_api_key="gateway-key")
    )


class _Resp:
    """Совместимость с прежними вызовами `_patch(resp=_Resp(...))`."""

    def __init__(self, status: int, payload=None):
        self.status_code, self.payload = status, payload or {}


def _patch(monkeypatch, *, resp=None, boom=None):
    """Подменяет ТРАНСПОРТ, а не клиент.

    ⚠️ Раньше тест патчил `llm_gateway.httpx.AsyncClient` — то есть знал, что модуль
    ходит в сеть сам. После перехода на общую базу такого атрибута нет, и подмена молча
    перестала бы что-либо значить: тест остался бы зелёным, ничего не проверяя.
    """
    seen: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["json"] = json.loads(request.content.decode("utf-8")) if request.content else None
        if boom is not None:
            raise httpx.ConnectError(str(boom))
        return httpx.Response(resp.status_code, json=resp.payload)

    transport = httpx.MockTransport(_handler)
    original = llm_gateway_mod.SidecarClient

    def _factory(**kw):
        client = original(**kw)
        client._transport = transport
        return client

    monkeypatch.setattr(llm_gateway_mod, "SidecarClient", _factory)
    return seen


_OK = {
    "choices": [{"message": {"content": "факт: любит кофе"}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 8, "total_tokens": 128},
}


@pytest.mark.asyncio
async def test_returns_text_and_usage(monkeypatch) -> None:
    """Usage обязан доехать: по нему списывается память пользователя."""
    seen = _patch(monkeypatch, resp=_Resp(200, _OK))

    text, usage = await chat_completion(
        _cfg(), messages=[{"role": "user", "content": "привет"}], model="gpt-4o-mini"
    )

    assert text == "факт: любит кофе"
    assert usage == {"prompt_tokens": 120, "completion_tokens": 8, "total_tokens": 128}
    assert seen["url"] == "http://agents:8090/v1/chat/completions"
    # httpx нормализует имена заголовков в нижний регистр.
    assert seen["headers"]["authorization"] == "Bearer gateway-key"


@pytest.mark.asyncio
async def test_missing_usage_does_not_pass_silently(monkeypatch) -> None:
    """Ответ без usage — вызов останется не списанным. Отдаём пустой словарь, а не
    выдумываем цифры: лучше ноль, чем неверная сумма."""
    _patch(monkeypatch, resp=_Resp(200, {"choices": [{"message": {"content": "ок"}}]}))

    text, usage = await chat_completion(_cfg(), messages=[], model="m")

    assert text == "ок"
    assert usage == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"boom": RuntimeError("сеть легла")},
        {"resp": _Resp(503)},
        {"resp": _Resp(200, {"choices": []})},
        {"resp": _Resp(200, {"нет": "choices"})},
    ],
)
async def test_failures_return_none(monkeypatch, kwargs) -> None:
    """None = «не смогли»; вызывающий (память) молча пропускает извлечение фактов —
    ронять ответ пользователю из-за служебного вызова несоразмерно."""
    _patch(monkeypatch, **kwargs)
    assert await chat_completion(_cfg(), messages=[], model="m") is None


@pytest.mark.asyncio
async def test_no_sidecar_url_means_no_call() -> None:
    assert await chat_completion(_cfg(url=""), messages=[], model="m") is None


@pytest.mark.asyncio
async def test_memory_accumulates_usage_from_dict() -> None:
    """Форма usage сменилась с объекта SDK на словарь — аккумулятор обязан читать ключи.

    Если бы он продолжил читать атрибуты, извлечение фактов молча стало бы бесплатным.
    """
    from service.services.analytics.application.memory_service import MemoryService

    out: dict = {}
    MemoryService._accumulate_usage(
        out, {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
    )

    assert out["prompt"] == 10 and out["completion"] == 3 and out["total"] == 13
