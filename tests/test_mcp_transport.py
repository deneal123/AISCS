"""Транспорт MCP и набор инструментов прогона.

Главное утверждение среза проверяется здесь, а не в адаптере: инструмент чужого сервера
попадает в ТОТ ЖЕ реестр, что и родной, и получает биллинг, потолок результата и таймаут
без единой ветки «если MCP». Тест на это (`test_mcp_tool_inherits_the_common_machinery`)
краснеет, стоит убрать слияние в резолвере.

Сеть не трогаем: `httpx.MockTransport` отвечает за сервер, а SSRF-проверка получает
настоящие имена (`localhost` внутренний, `example.com` публичный).
"""

from __future__ import annotations

import json

import httpx
import pytest

from service.domain.capabilities import tool_registry
from service.infrastructure.mcp import runtime as mcp_runtime
from service.infrastructure.mcp import transport as mcp_transport
from service.infrastructure.mcp.adapter import BILLING_NAME
from service.infrastructure.mcp.circuit import circuit_breaker
from service.infrastructure.mcp.server_ref import ServerRef
from service.infrastructure.mcp.transport import (
    McpError,
    McpProtocolError,
    McpRemoteError,
    McpSession,
    McpTimeoutError,
    _parse_body,
)
from service.infrastructure.sidecar import set_correlation_id
from service.shared.net_guard import UnsafeUrlError

SERVER = ServerRef(id="acme", url="https://mcp.example.com/rpc")


def _rpc_ok(result: dict) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def _session(handler, timeout: float = 5.0) -> McpSession:
    return McpSession(SERVER, httpx.AsyncClient(transport=httpx.MockTransport(handler)), timeout)


# --- разбор ответа -----------------------------------------------------------------


def test_plain_json_body_is_parsed() -> None:
    assert _parse_body('{"result": {"ok": 1}}') == {"result": {"ok": 1}}


def test_sse_progress_events_do_not_masquerade_as_the_result() -> None:
    """Сервер вправе прислать уведомления перед результатом — берём именно результат."""
    body = (
        'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"p":1}}\n\n'
        'data: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n'
    )
    assert _parse_body(body) == {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}


def test_empty_body_is_an_error_not_an_empty_result() -> None:
    with pytest.raises(McpError):
        _parse_body("   ")


# --- сессия ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_normalizes_protocol_schema_name() -> None:
    """`inputSchema` протокола → `input_schema` спеки. Иначе схема потеряется молча."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _rpc_ok({"tools": [{"name": "search", "inputSchema": {"type": "object"}}]})

    tools = await _session(handler).list_tools()
    assert tools == [{"name": "search", "description": "", "input_schema": {"type": "object"}}]


@pytest.mark.asyncio
async def test_session_id_from_initialize_is_sent_back() -> None:
    """Без возврата идентификатора сессии вторая же команда получает 404."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("mcp-session-id", ""))
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": {}},
            headers={"Mcp-Session-Id": "s-42"},
        )

    session = _session(handler)
    await session.initialize()
    await session.list_tools()
    assert seen[0] == "" and seen[-1] == "s-42"


@pytest.mark.asyncio
async def test_mcp_call_propagates_correlation_and_uses_remaining_deadline(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["correlation"] = request.headers.get("x-correlation-id")
        seen["timeout"] = request.extensions["timeout"]["connect"]
        return _rpc_ok({"tools": []})

    monkeypatch.setattr(mcp_transport.deadline, "clamp", lambda _want: 1.25)
    set_correlation_id("corr-s12")
    try:
        await _session(handler, timeout=5.0).list_tools()
    finally:
        set_correlation_id(None)
    assert seen == {"correlation": "corr-s12", "timeout": 1.25}


@pytest.mark.asyncio
async def test_mcp_transport_failure_taxonomy_and_tool_call_no_retry() -> None:
    calls = 0

    def remote(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"error": "unavailable"})

    with pytest.raises(McpRemoteError) as caught:
        await _session(remote).call_tool("search", "{}")
    assert caught.value.retryable
    assert calls == 1, "tools/call must never be retried by the MCP client"

    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("late")

    with pytest.raises(McpTimeoutError):
        await _session(timeout).list_tools()
    with pytest.raises(McpProtocolError):
        _parse_body("not-json")


@pytest.mark.asyncio
async def test_tool_result_blocks_become_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _rpc_ok(
            {"content": [{"type": "text", "text": "привет"}, {"type": "image", "data": "…"}]}
        )

    text = await _session(handler).call_tool("search", '{"q": "x"}')
    assert "привет" in text and "не текстовое" in text


@pytest.mark.asyncio
async def test_tool_error_is_named_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _rpc_ok({"isError": True, "content": [{"type": "text", "text": "нет доступа"}]})

    assert "ошибку" in await _session(handler).call_tool("search", "{}")


@pytest.mark.asyncio
async def test_broken_arguments_do_not_crash_the_call() -> None:
    """Модель прислала не-JSON в аргументах — зовём с пустыми, а не роняем ход."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content.decode()))
        return _rpc_ok({"content": [{"type": "text", "text": "ok"}]})

    await _session(handler).call_tool("search", "не json")
    assert seen[0]["params"]["arguments"] == {}


@pytest.mark.asyncio
async def test_protocol_error_is_raised_not_returned_as_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "error": {"message": "нет такого метода"}}
        )

    with pytest.raises(McpError):
        await _session(handler).list_tools()


@pytest.mark.asyncio
async def test_oversized_body_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Валидный JSON, добитый пробелами: проверяем ПОТОЛОК, а не разбор.
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}).encode()
        padding = b" " * (mcp_transport.MAX_RESPONSE_BYTES + 1 - len(body))
        return httpx.Response(200, content=body + padding)

    with pytest.raises(McpError):
        await _session(handler).list_tools()


# --- безопасность подключения ------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_host_is_refused_before_any_request() -> None:
    """🔴 Внутренний адрес не открывается вовсе: за ним Postgres, Redis, MinIO и сайдкары."""
    with pytest.raises(UnsafeUrlError):
        await mcp_transport.open_session(
            ServerRef(id="inner", url="http://localhost:8090/rpc"), 5.0
        )


@pytest.mark.asyncio
async def test_redirect_is_refused_and_never_followed() -> None:
    """🔴 3xx на внутренний хост — обход проверки адреса. Не идём и не молчим."""
    visited: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        visited.append(str(request.url))
        # ⚠️ Тело ВАЛИДНОЕ: иначе тест краснел бы из-за неразобранного ответа и молчал о
        # том, отвергнут редирект или нет.
        return httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1:6379/"},
            json={"jsonrpc": "2.0", "id": 1, "result": {"tools": []}},
        )

    with pytest.raises(McpError):
        await _session(handler).list_tools()
    assert visited == [SERVER.url]


# --- набор инструментов прогона ----------------------------------------------------


class _FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeSession:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    async def list_tools(self) -> list[dict]:
        return [{"name": n, "description": "", "input_schema": {}} for n in self._names]

    async def call_tool(self, name: str, arguments: str) -> str:
        return f"вызван {name}"


def _declare(monkeypatch, servers: list[dict], sessions: dict[str, list[str] | None]) -> list:
    """Объявить серверы админом и подменить подключение. Возвращает список клиентов."""
    clients: list[_FakeClient] = []

    async def fake_open(server, timeout):
        names = sessions.get(server.id)
        if names is None:
            raise RuntimeError("сервер лежит")
        client = _FakeClient()
        clients.append(client)
        return _FakeSession(names), client

    monkeypatch.setattr(mcp_runtime, "_settings", lambda: (True, servers, 5.0))
    monkeypatch.setattr(mcp_runtime, "open_session", fake_open)
    return clients


@pytest.mark.asyncio
async def test_no_allowed_servers_means_no_network_at_all(monkeypatch) -> None:
    """Обычный чат в сеть не ходит: пустое разрешение — мгновенный no-op."""

    async def explode(server, timeout):
        raise AssertionError("подключение при пустом разрешении")

    monkeypatch.setattr(
        mcp_runtime, "_settings", lambda: (True, [{"id": "acme", "url": "https://x.example"}], 5.0)
    )
    monkeypatch.setattr(mcp_runtime, "open_session", explode)
    async with mcp_runtime.open_mcp_tools(None):
        assert mcp_runtime.current_specs() == ()


@pytest.mark.asyncio
async def test_dead_server_is_skipped_and_the_run_continues(monkeypatch) -> None:
    declared = [
        {"id": "alive", "url": "https://a.example"},
        {"id": "dead", "url": "https://b.example"},
    ]
    clients = _declare(monkeypatch, declared, {"alive": ["search"], "dead": None})
    async with mcp_runtime.open_mcp_tools(["alive", "dead"]) as specs:
        assert [s.name for s in specs] == ["mcp_alive__search"]
    assert all(c.closed for c in clients), "соединения не закрыты вместе с прогоном"


@pytest.mark.asyncio
async def test_integration_health_trace_is_aggregate_only(monkeypatch) -> None:
    declared = [{"id": "acme", "url": "https://private.example/never-expose"}]
    _declare(monkeypatch, declared, {"acme": ["search"]})
    monkeypatch.setattr(mcp_runtime, "_resilience_settings", lambda: ("observe", 3, 60.0))
    async with mcp_runtime.open_mcp_tools(["acme"]):
        event = mcp_runtime.current_health_event()
        assert event is not None
        health = event.metadata["integration_health"]
        assert health["stage"] == "discovery"
        assert health["servers"] == 1 and health["tools"] == 1
        assert "private.example" not in str(health)


@pytest.mark.asyncio
async def test_server_failing_at_discovery_releases_its_connection(monkeypatch) -> None:
    """Подключились, а список не отдали — соединение всё равно закрываем."""
    client = _FakeClient()

    class _Broken:
        async def list_tools(self):
            raise RuntimeError("сервер сломался на обходе")

    async def fake_open(server, timeout):
        return _Broken(), client

    monkeypatch.setattr(
        mcp_runtime, "_settings", lambda: (True, [{"id": "acme", "url": "https://x.example"}], 5.0)
    )
    monkeypatch.setattr(mcp_runtime, "open_session", fake_open)
    async with mcp_runtime.open_mcp_tools(["acme"]) as specs:
        assert specs == ()
    assert client.closed


@pytest.mark.asyncio
async def test_discovery_retries_once_and_circuit_observe_does_not_skip(monkeypatch) -> None:
    circuit_breaker.reset()
    attempts = 0
    client = _FakeClient()

    async def flaky_open(_server, _timeout):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise McpTimeoutError("late")
        return _FakeSession(["search"]), client

    monkeypatch.setattr(mcp_runtime, "open_session", flaky_open)
    try:
        first = await mcp_runtime._connect(SERVER, 5.0, mode="observe", threshold=1, cooldown=60)
        assert first.reason == "timeout"
        assert attempts == 2, "only one safe discovery retry is allowed"

        blocked = await mcp_runtime._connect(SERVER, 5.0, mode="enforce", threshold=1, cooldown=60)
        assert blocked.circuit_open and attempts == 2

        observed = await mcp_runtime._connect(SERVER, 5.0, mode="observe", threshold=1, cooldown=60)
        assert [spec.name for spec in observed.specs] == ["mcp_acme__search"]
        assert attempts == 3
        await observed.client.aclose()
    finally:
        circuit_breaker.reset()


@pytest.mark.asyncio
async def test_disabled_globally_means_no_servers(monkeypatch) -> None:
    """⚠️ Подключение подменено РАБОЧИМ: иначе «выключено» неотличимо от «не отвечает»."""
    declared = [{"id": "acme", "url": "https://x.example"}]
    _declare(monkeypatch, declared, {"acme": ["search"]})
    monkeypatch.setattr(mcp_runtime, "_settings", lambda: (False, declared, 5.0))
    async with mcp_runtime.open_mcp_tools(["acme"]) as specs:
        assert specs == ()


@pytest.mark.asyncio
async def test_total_tool_cap_protects_the_context_budget(monkeypatch) -> None:
    """Схемы уезжают модели в КАЖДОМ запросе — потолок общий, а не только на сервер."""
    # ⚠️ ТРИ сервера: два по потолку сервера дают ровно 40, и общий потолок был бы не при
    # чём — тест зеленел бы, даже если его снять.
    names = [f"t{i}" for i in range(mcp_runtime.MAX_TOOLS_TOTAL)]
    declared = [{"id": sid, "url": f"https://{sid}.example"} for sid in ("a", "b", "c")]
    _declare(monkeypatch, declared, {"a": names, "b": names, "c": names})
    async with mcp_runtime.open_mcp_tools(["a", "b", "c"]) as specs:
        assert len(specs) == mcp_runtime.MAX_TOOLS_TOTAL


@pytest.mark.asyncio
async def test_specs_do_not_leak_out_of_the_run(monkeypatch) -> None:
    declared = [{"id": "acme", "url": "https://a.example"}]
    _declare(monkeypatch, declared, {"acme": ["search"]})
    async with mcp_runtime.open_mcp_tools(["acme"]):
        assert mcp_runtime.current_specs()
    assert mcp_runtime.current_specs() == ()


# --- 🔴 главное утверждение среза --------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_tool_inherits_the_common_machinery(monkeypatch) -> None:
    """Чужой инструмент не получает СВОЕЙ машинерии.

    Он должен появиться в общем реестре и в наборе, выдаваемом модели, и по нему должны
    находиться надбавка, потолок результата и таймаут — теми же функциями, что для родного.
    Пропади слияние в резолвере — тест краснеет, а способность станет неоплаченной и
    невидимой для лимитов.
    """
    declared = [{"id": "acme", "url": "https://a.example"}]
    _declare(monkeypatch, declared, {"acme": ["search"]})

    class _Native:
        name = "fetch_url"

    async with mcp_runtime.open_mcp_tools(["acme"]):
        name = "mcp_acme__search"
        assert name in tool_registry.tool_specs()
        assert tool_registry.tool_billing_names()[name] == BILLING_NAME
        assert tool_registry.tool_result_limit(name) == tool_registry.tool_result_limit("fetch_url")
        assert tool_registry.tool_timeout(name) == tool_registry.tool_timeout("fetch_url")

        resolved = tool_registry.resolve_toolset([_Native()], None)
        assert [t.name for t in resolved.tools] == ["fetch_url", name]


@pytest.mark.asyncio
async def test_toolless_agent_stays_toolless(monkeypatch) -> None:
    """Агент, объявивший ноль инструментов, сделан таким намеренно — не меняем его."""
    declared = [{"id": "acme", "url": "https://a.example"}]
    _declare(monkeypatch, declared, {"acme": ["search"]})
    async with mcp_runtime.open_mcp_tools(["acme"]):
        assert tool_registry.resolve_toolset([], None).tools == []


def test_allowlist_is_ambient_and_never_reaches_execute() -> None:
    """Список серверов — окружение прогона: попади он в kwargs, упал бы КАЖДЫЙ прогон."""
    from service.schemas.run import AMBIENT_FIELDS, AgentRunInput

    payload = AgentRunInput(text="привет", thread_id="t1", mcp_server_ids=["acme"])
    assert "mcp_server_ids" in AMBIENT_FIELDS
    assert "mcp_server_ids" not in payload.to_execute_kwargs()
