"""Общая база клиента сайдкара: единое поведение вместо пяти разных.

Что здесь закрепляется и почему это не косметика:

* отказ ВСЕГДА исключение, а не пустое значение — fail-open главный источник немых
  поломок (вызывающий принимает пустоту за «данных нет» и идёт дальше);
* 4xx отделён от 5xx: «пришлите другой файл» модель может исправить сама, «сервис лежит» —
  нет. Раньше оба сводились к одному сообщению;
* транспортный сбой и HTTP-ошибка ведут себя ОДИНАКОВО. У клиента duckdb было наоборот:
  HTTP-ошибка становилась значением, а сетевая улетала исключением — из одного и того же
  метода;
* сквозной идентификатор уходит в заголовке. Без него историю одного сообщения нельзя
  собрать из логов разных сервисов.

⚠️ Тесты гоняют РАБОЧИЙ код через `httpx.MockTransport`, а не повторяют его логику у
себя. Первая версия этого файла именно повторяла — и проверяла бы собственную копию,
оставаясь зелёной при любой поломке клиента.
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
    set_correlation_id,
)


def _client(handler, *, timeout: float = 5.0) -> SidecarClient:
    return SidecarClient(
        service="probe",
        base_url="http://probe:8080",
        timeout=timeout,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_4xx_is_bad_request_not_unavailable():
    """4xx — вина ВЫЗЫВАЮЩЕГО, и типом это должно быть видно.

    Свести 4xx и 5xx в один тип значило бы отвечать «сервис недоступен» там, где
    достаточно приложить другой файл.
    """
    client = _client(
        lambda _r: httpx.Response(415, json={"error": "unsupported_format", "detail": ".docx"})
    )

    with pytest.raises(SidecarBadRequest) as exc:
        await client.request_json("POST", "/query", json_body={})

    assert exc.value.code == "unsupported_format"
    assert exc.value.detail == ""
    assert ".docx" not in str(exc.value)
    assert exc.value.service == "probe"


@pytest.mark.asyncio
async def test_5xx_is_unavailable():
    client = _client(lambda _r: httpx.Response(500, json={"error": "query_failed", "detail": "b"}))

    with pytest.raises(SidecarUnavailable) as exc:
        await client.request_json("POST", "/query", json_body={})

    assert exc.value.code == "query_failed"


@pytest.mark.asyncio
async def test_504_is_timeout_not_generic_failure():
    """Серверный дедлайн — это срок, а не поломка: сосед сам решил, что не успевает."""
    client = _client(lambda _r: httpx.Response(504, json={"error": "query_timeout", "detail": ""}))

    with pytest.raises(SidecarTimeout):
        await client.request_json("POST", "/query", json_body={})


@pytest.mark.asyncio
async def test_transport_failure_is_also_an_exception():
    """Сетевой сбой и HTTP-ошибка ведут себя ОДИНАКОВО.

    У клиента duckdb было иначе: HTTP-ошибка становилась значением `{"error": ...}`, а
    сетевая улетала наверх — один метод отвечал по-разному в зависимости от того, где
    сломалось, и вызывающий не мог написать один обработчик.
    """

    def _refuse(_request):
        raise httpx.ConnectError("connection refused")

    client = _client(_refuse)

    with pytest.raises(SidecarUnavailable) as exc:
        await client.request_json("POST", "/query", json_body={})

    assert exc.value.code == "transport_error"


@pytest.mark.asyncio
async def test_client_timeout_is_a_timeout():
    def _hang(_request):
        raise httpx.ReadTimeout("too slow")

    client = _client(_hang)

    with pytest.raises(SidecarTimeout) as exc:
        await client.request_json("POST", "/query", json_body={})

    assert exc.value.code == "timeout"


@pytest.mark.asyncio
async def test_success_returns_body():
    client = _client(lambda _r: httpx.Response(200, json={"rows": [[1]], "row_count": 1}))

    body = await client.request_json("POST", "/query", json_body={})

    assert body == {"rows": [[1]], "row_count": 1}


@pytest.mark.asyncio
async def test_success_returns_binary_body_with_same_correlation_contract():
    seen: dict[str, str] = {}

    def _capture(request):
        seen.update(request.headers)
        return httpx.Response(200, content=b"xlsx-bytes")

    set_correlation_id("trace-binary")
    try:
        body = await _client(_capture).request_bytes("POST", "/convert", content=b"xls")
    finally:
        set_correlation_id(None)

    assert body == b"xlsx-bytes"
    assert seen[CORRELATION_HEADER.lower()] == "trace-binary"


@pytest.mark.asyncio
async def test_correlation_header_is_sent_when_set():
    """Идентификатор доезжает до соседа — иначе логи двух сервисов не связать."""
    seen: dict[str, str] = {}

    def _capture(request):
        seen.update(request.headers)
        return httpx.Response(200, json={"ok": True})

    set_correlation_id("trace-42")
    try:
        await _client(_capture).request_json("POST", "/query", json_body={})
    finally:
        set_correlation_id(None)

    assert seen.get(CORRELATION_HEADER.lower()) == "trace-42"


@pytest.mark.asyncio
async def test_no_correlation_header_when_unset():
    """Пустой идентификатор НЕ шлём: заголовок-прочерк врал бы о наличии трассы."""
    seen: dict[str, str] = {}

    def _capture(request):
        seen.update(request.headers)
        return httpx.Response(200, json={"ok": True})

    set_correlation_id(None)
    await _client(_capture).request_json("POST", "/query", json_body={})

    assert CORRELATION_HEADER.lower() not in seen


@pytest.mark.asyncio
async def test_unconfigured_service_fails_loudly():
    """Пустой адрес — отказ, а не тихий «ничего не делаем».

    Незаданный адрес это ошибка конфигурации; молчаливое «ок» спрятало бы её до прода.
    """
    client = SidecarClient(service="probe", base_url="", timeout=1.0)

    assert client.available is False
    with pytest.raises(SidecarUnavailable) as exc:
        await client.request_json("GET", "/health")

    assert exc.value.code == "not_configured"


def test_error_body_of_unmigrated_service_is_not_retained():
    """Сервис, ещё не приведённый к регламенту, отвечает по-своему — это не повод падать.

    Раскатка идёт по сервисам, а не одномоментно: клиент обязан пережить чужую форму
    ошибки и хотя бы донести текст.
    """
    client = SidecarClient(service="probe", base_url="http://x", timeout=1.0)

    code, detail = client._read_error(httpx.Response(500, text="Internal Server Error"))
    assert code == ""
    assert detail == ""

    code, _ = client._read_error(httpx.Response(422, json={"detail": [{"loc": ["body"]}]}))
    assert code == ""
