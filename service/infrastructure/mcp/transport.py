"""Сессия к MCP-серверу: JSON-RPC поверх streamable-HTTP.

⚠️ ЗАЧЕМ СВОЙ КЛИЕНТ, а не `agents.mcp` из SDK. Готовый подключается через
`Agent(mcp_servers=…)`, а это исполняется только на SDK-пути (`runners/sdk_run.py`);
живой путь для mws/openrouter/gigachat/routerai — `chat_run.py`. Взять готовое значило бы
перевести живой путь на SDK и потерять фейловер, пиннинг провайдера между раундами и
per-provider `include_usage`. Протокол же здесь — три метода JSON-RPC.

🔴 SSRF-ПРОВЕРКА ОБЯЗАТЕЛЬНА, ХОТЯ АДРЕС ЗАДАЁТ АДМИН. Внутренняя сеть открыта по
топологии: Postgres, Redis, MinIO, Qdrant и все сайдкары не спрашивают аутентификации, и
опечатка в адресе превращает MCP-клиент в читалку внутреннего периметра. Редиректы НЕ
ходим вовсе: 3xx на внутренний хост — классический обход проверки, а отказ проще и
надёжнее, чем перепроверка каждого хопа.

⚠️ Проверка снимается ОДИН РАЗ, на открытии. От DNS rebinding это не спасает — на уровне
httpx закрыть его нечем, и заявлять обратное было бы хуже, чем не заявлять.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from service.infrastructure.mcp.server_ref import ServerRef
from service.infrastructure.sidecar import CORRELATION_HEADER, get_correlation_id
from service.shared import deadline
from service.shared.net_guard import assert_public_host

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "gpthub-agents", "version": "1.0"}

# Потолок тела ответа. Чужой сервер может отдать сколько угодно; распаковывать это в
# память процесса, обслуживающего всех арендаторов, нельзя.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class McpError(Exception):
    """Base MCP failure with a bounded category and retryability contract."""

    code = "mcp_error"
    retryable = False


class McpTransportError(McpError):
    code = "transport"
    retryable = True


class McpTimeoutError(McpError):
    code = "timeout"
    retryable = True


class McpProtocolError(McpError):
    code = "protocol"


class McpRemoteError(McpError):
    code = "remote"

    def __init__(self, status: int | None = None, detail: str = "") -> None:
        # Remote JSON-RPC and HTTP bodies are untrusted and may echo arguments,
        # schemas, URLs, or user data.  Keep only the bounded category in the
        # exception retained by the runtime.
        super().__init__(self.code)
        self.status = int(status) if status is not None else None
        self.retryable = self.status is not None and self.status >= 500


class McpCircuitOpen(McpError):
    code = "circuit_open"


def _headers(server: ServerRef, session_id: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        # Streamable-HTTP отвечает либо JSON, либо SSE — принимаем оба и разбираем по факту.
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }
    if server.auth_token:
        headers[server.auth_header or "Authorization"] = server.auth_token
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if correlation_id := get_correlation_id():
        headers[CORRELATION_HEADER] = correlation_id
    return headers


def _parse_body(text: str) -> dict[str, Any]:
    """Тело ответа → JSON-RPC объект. SSE-обёртку снимаем, если она есть.

    ⚠️ Берём ПОСЛЕДНЕЕ событие с `result`/`error`: сервер вправе прислать перед ним
    уведомления о прогрессе, и первое попавшееся `data:` результатом не является.
    """
    body = (text or "").strip()
    if not body:
        raise McpProtocolError("пустой ответ")
    if not body.startswith("data:"):
        try:
            return json.loads(body)
        except ValueError as exc:
            raise McpProtocolError("ответ не является JSON") from exc
    found: dict[str, Any] | None = None
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            item = json.loads(line[5:].strip())
        except ValueError:
            continue
        if isinstance(item, dict) and ("result" in item or "error" in item):
            found = item
    if found is None:
        raise McpProtocolError("в потоке событий нет результата")
    return found


class McpSession:
    """Одно соединение с сервером на время прогона."""

    def __init__(self, server: ServerRef, client: httpx.AsyncClient, timeout_sec: float) -> None:
        self._server = server
        self._client = client
        self._timeout = timeout_sec
        self._session_id = ""
        self._next_id = 0

    async def _post(self, payload: dict, *, timeout_sec: float) -> httpx.Response:
        try:
            response = await self._client.post(
                self._server.url,
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=_headers(self._server, self._session_id),
                timeout=deadline.clamp(timeout_sec),
            )
        except httpx.TimeoutException:
            raise McpTimeoutError("timeout") from None
        except httpx.HTTPError:
            raise McpTransportError("transport") from None
        if 300 <= response.status_code < 400:
            # 🔴 Редирект ОТВЕРГАЕМ, а не идём по нему: проверка адреса сделана на
            # открытии сессии, и 3xx на внутренний хост — классический способ её обойти.
            # Отказ проще перепроверки каждого хопа и не оставляет щели между ними.
            raise McpRemoteError(response.status_code, "редирект не поддерживается")
        if response.status_code >= 400:
            raise McpRemoteError(response.status_code)
        # Идентификатор сессии сервер выдаёт на `initialize` и ждёт обратно во всех
        # последующих запросах; без него вторая же команда получает 404.
        new_id = response.headers.get("mcp-session-id") or ""
        if new_id:
            self._session_id = new_id
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise McpProtocolError("ответ больше допустимого")
        return response

    async def _rpc(self, method: str, params: dict | None, *, timeout_sec: float) -> dict:
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        response = await self._post(payload, timeout_sec=timeout_sec)
        message = _parse_body(response.text)
        if "error" in message:
            raise McpRemoteError()
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    async def _notify(self, method: str) -> None:
        # Уведомление ответа не требует; сбой на нём прогон не роняет.
        try:
            await self._post({"jsonrpc": "2.0", "method": method}, timeout_sec=self._timeout)
        except Exception:  # noqa: BLE001
            logger.debug("MCP %s: уведомление %s не доставлено", self._server.id, method)

    async def initialize(self, *, timeout_sec: float | None = None) -> None:
        await self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
            timeout_sec=timeout_sec or self._timeout,
        )
        await self._notify("notifications/initialized")

    async def list_tools(self, *, timeout_sec: float | None = None) -> list[dict]:
        """Инструменты сервера в форме, которую ждёт адаптер.

        ⚠️ Имя схемы у протокола `inputSchema`, у нашей спеки — `input_schema`. Приводим
        ЗДЕСЬ: адаптер не должен знать протокола, иначе его нельзя проверить без сервера.
        """
        result = await self._rpc("tools/list", {}, timeout_sec=timeout_sec or self._timeout)
        items = result.get("tools")
        if not isinstance(items, list):
            return []
        return [
            {
                "name": item.get("name"),
                "description": item.get("description") or "",
                "input_schema": item.get("inputSchema") or item.get("input_schema"),
            }
            for item in items
            if isinstance(item, dict)
        ]

    async def call_tool(self, name: str, arguments_json: str) -> str:
        try:
            arguments = json.loads(arguments_json or "{}")
        except ValueError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        result = await self._rpc(
            "tools/call", {"name": name, "arguments": arguments}, timeout_sec=self._timeout
        )
        return _content_text(result)


def _content_text(result: dict) -> str:
    """Блоки контента → текст. Не-текстовые описываем словами, а не выбрасываем."""
    blocks = result.get("content")
    if not isinstance(blocks, list):
        return json.dumps(result, ensure_ascii=False)
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text") or ""))
        else:
            parts.append(f"[{kind or 'данные'}: содержимое не текстовое]")
    text = "\n".join(p for p in parts if p)
    if result.get("isError"):
        return f"Инструмент вернул ошибку: {text or 'без описания'}"
    return text


async def open_session(
    server: ServerRef, timeout_sec: float
) -> tuple[McpSession, httpx.AsyncClient]:
    """Проверить адрес, подключиться, поздороваться. Клиента закрывает вызывающий."""
    host = urlparse(server.url).hostname or ""
    await assert_public_host(host)
    client = httpx.AsyncClient(follow_redirects=False, timeout=timeout_sec)
    try:
        session = McpSession(server, client, timeout_sec)
        await session.initialize()
    except BaseException:
        await client.aclose()
        raise
    return session, client
