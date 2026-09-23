"""Общая база клиента сайдкара в backend: единое поведение вместо восемнадцати.

Вторая копия базы (первая — в `agents/service/infrastructure/sidecar.py`). Общего пакета
не заводим осознанно, тем же решением, что и по контракту `/run`.

Что закрепляется:

* отказ ВСЕГДА исключение, а не пустое значение — fail-open главный источник немых
  поломок: вызывающий принимает пустоту за «данных нет» и идёт дальше;
* 4xx отделён от 5xx: «формат не поддержан» вызывающий может исправить, «сервис лежит» —
  нет;
* корреляция берётся из уже существующего контекста backend и уходит заголовком. До
  этого её не пробрасывал НИ ОДИН из 18 клиентов.
"""

from __future__ import annotations

import httpx
import pytest

from service.infrastructure.sidecar import (
    CORRELATION_HEADER,
    SidecarBadRequest,
    SidecarClient,
    SidecarTimeout,
    SidecarUnavailable,
)
from service.shared.observability.context import set_correlation_context


def _client(handler, *, api_key: str = "") -> SidecarClient:
    return SidecarClient(
        service="probe",
        base_url="http://probe:8080",
        timeout=5.0,
        api_key=api_key,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_4xx_is_bad_request_not_unavailable():
    """4xx — вина ВЫЗЫВАЮЩЕГО, и типом это должно быть видно."""
    client = _client(
        lambda _r: httpx.Response(415, json={"error": "unsupported_format", "detail": ".docx"})
    )

    with pytest.raises(SidecarBadRequest) as exc:
        await client.request_json("POST", "/parse")

    assert exc.value.code == "unsupported_format"
    assert exc.value.detail == ".docx"


@pytest.mark.asyncio
async def test_5xx_is_unavailable():
    client = _client(lambda _r: httpx.Response(500, json={"error": "parse_failed", "detail": "x"}))

    with pytest.raises(SidecarUnavailable):
        await client.request_json("POST", "/parse")


@pytest.mark.asyncio
async def test_504_is_timeout():
    """Серверный дедлайн — срок, а не поломка: сосед сам решил, что не успевает."""
    client = _client(lambda _r: httpx.Response(504, json={"error": "parse_timeout", "detail": ""}))

    with pytest.raises(SidecarTimeout):
        await client.request_json("POST", "/parse")


@pytest.mark.asyncio
async def test_transport_failure_is_also_an_exception():
    """Сетевой сбой и HTTP-ошибка ведут себя ОДИНАКОВО — один обработчик у вызывающего."""

    def _refuse(_request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(SidecarUnavailable) as exc:
        await _client(_refuse).request_json("POST", "/parse")

    assert exc.value.code == "transport_error"


@pytest.mark.asyncio
async def test_correlation_header_is_sent_from_backend_context():
    """Идентификатор берётся из контекста backend, который ставит воркер.

    ⚠️ Именно из НЕГО, а не из своего ContextVar: в backend корреляция уже существует
    (`shared/observability/context`), и заводить вторую значило бы сшивать логи по двум
    разным ключам.
    """
    seen: dict[str, str] = {}

    def _capture(request):
        seen.update(request.headers)
        return httpx.Response(200, json={"ok": True})

    set_correlation_context(correlation_id="job-77", trace_id=None)
    try:
        await _client(_capture).request_json("GET", "/health")
    finally:
        set_correlation_context(correlation_id=None, trace_id=None)

    assert seen.get(CORRELATION_HEADER.lower()) == "job-77"


@pytest.mark.asyncio
async def test_api_key_is_sent_when_configured():
    seen: dict[str, str] = {}

    def _capture(request):
        seen.update(request.headers)
        return httpx.Response(200, json={"ok": True})

    await _client(_capture, api_key="secret").request_json("GET", "/health")

    assert seen.get("authorization") == "Bearer secret"


@pytest.mark.asyncio
async def test_unconfigured_service_fails_loudly():
    """Пустой адрес — отказ, а не тихий «ничего не делаем»."""
    client = SidecarClient(service="probe", base_url="", timeout=1.0)

    assert client.available is False
    with pytest.raises(SidecarUnavailable) as exc:
        await client.request_json("GET", "/health")

    assert exc.value.code == "not_configured"


def test_error_body_of_unmigrated_service_does_not_break_parsing():
    """Сервис вне регламента отвечает по-своему — это не повод падать."""
    client = SidecarClient(service="probe", base_url="http://x", timeout=1.0)

    code, detail = client._read_error(httpx.Response(500, text="Internal Server Error"))

    assert code == ""
    assert "Internal Server Error" in detail
