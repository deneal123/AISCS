"""MCP-инструменты, доступные ОДНОМУ прогону.

Набор зависит от арендатора (какие серверы ему разрешены) и от того, что эти серверы
сегодня отвечают, — то есть он не статический и в реестр модулей не помещается. Живёт в
окружении прогона, как провайдерная политика и дедлайн: протаскивать его аргументом
пришлось бы через полтора десятка сигнатур ради списка, который читают в одном месте.

⚠️ Обход серверов делается ОДИН РАЗ на прогон, на входе. Не лениво при первом обращении:
разрешение набора инструментов происходит на каждом раунде цикла, и ленивый вариант
означал бы поход в сеть из синхронного кода посреди диалога.

Сервер, который не ответил, ПРОПУСКАЕТСЯ, а не роняет прогон: чужой сервис лежит — это
его дело, а пользователю нужен ответ.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from service.domain.capabilities.tool_spec import ToolSpec
from service.events import AgentEvent, EventType
from service.infrastructure.mcp.adapter import mcp_tool_specs
from service.infrastructure.mcp.circuit import circuit_breaker
from service.infrastructure.mcp.server_ref import ServerRef, resolve_servers
from service.infrastructure.mcp.transport import McpError, open_session
from service.shared import deadline

logger = logging.getLogger(__name__)

# Потолок на ВЕСЬ прогон, поверх потолка на сервер. Схемы уезжают модели в каждом
# запросе, и пять разговорчивых серверов вытеснят из бюджета контекста файл пользователя.
MAX_TOOLS_TOTAL = 40

_SPECS: ContextVar[tuple[ToolSpec, ...]] = ContextVar("gpthub_mcp_specs", default=())
_HEALTH: ContextVar[dict[str, Any] | None] = ContextVar("gpthub_mcp_health", default=None)


def current_specs() -> tuple[ToolSpec, ...]:
    """Спеки MCP-инструментов этого прогона. Пусто — MCP не задействован."""
    return _SPECS.get()


def current_tools() -> list:
    """Объекты инструментов для выдачи модели."""
    return [spec.tool for spec in _SPECS.get()]


def _settings() -> tuple[bool, list, float]:
    from service.settings import config
    from service.shared.agent_settings import runtime_settings

    enabled = bool(runtime_settings.get_agents("mcp_enabled", config.agents.mcp_enabled))
    # Объявление серверов — админ-структура: адрес и секрет задаёт админ, а не арендатор.
    declared = runtime_settings.get_agents("mcp_servers", config.agents.mcp_servers) or []
    timeout = float(
        runtime_settings.get_agents("mcp_timeout_sec", config.agents.mcp_timeout_sec) or 20.0
    )
    return enabled, list(declared), timeout


def _resilience_settings() -> tuple[str, int, float]:
    from service.settings import config
    from service.shared.agent_settings import runtime_settings

    mode = str(
        runtime_settings.get_agents("mcp_resilience_mode", config.agents.mcp_resilience_mode)
        or "observe"
    ).lower()
    if mode not in {"off", "observe", "enforce"}:
        mode = "observe"
    try:
        threshold = max(
            1,
            int(
                runtime_settings.get_agents(
                    "mcp_circuit_failure_threshold", config.agents.mcp_circuit_failure_threshold
                )
            ),
        )
    except (TypeError, ValueError):
        threshold = 3
    try:
        cooldown = max(
            1.0,
            float(
                runtime_settings.get_agents(
                    "mcp_circuit_cooldown_sec", config.agents.mcp_circuit_cooldown_sec
                )
            ),
        )
    except (TypeError, ValueError):
        cooldown = 60.0
    return mode, threshold, cooldown


@dataclass(slots=True)
class _Connection:
    specs: list[ToolSpec]
    client: object | None
    reason: str = ""
    circuit_open: bool = False


def _reason(exc: Exception) -> str:
    code = exc.code if isinstance(exc, McpError) else "unknown"
    allowed = {"transport", "timeout", "protocol", "remote", "circuit_open"}
    return code if code in allowed else "unknown"


def _retryable(exc: Exception) -> bool:
    return bool(getattr(exc, "retryable", False))


async def _connect(
    server: ServerRef, timeout: float, *, mode: str, threshold: int, cooldown: float
) -> _Connection:
    """Discover a server with one safe retry; never retry a tools/call invocation."""
    if mode != "off" and circuit_breaker.open(server.id) and mode == "enforce":
        logger.info("MCP discovery skipped code=circuit_open")
        return _Connection([], None, reason="circuit_open", circuit_open=True)

    last_error: Exception | None = None
    for attempt in range(2):
        client = None
        try:
            session, client = await open_session(server, deadline.clamp(timeout))
            descriptors = await session.list_tools()
            specs = mcp_tool_specs(server, descriptors, session.call_tool)
            if not specs:
                await client.aclose()
                return _Connection([], None, reason="no_tools")
            if mode != "off":
                circuit_breaker.succeeded(server.id)
            return _Connection(specs, client)
        except Exception as exc:  # noqa: BLE001 — foreign discovery must fail open
            last_error = exc
            if client is not None:
                await client.aclose()
            if not _retryable(exc) or attempt:
                break
            logger.info("MCP discovery retry code=%s", _reason(exc))

    reason = _reason(last_error or RuntimeError("unknown"))
    if mode != "off" and _retryable(last_error or RuntimeError()):
        circuit_breaker.failed(server.id, threshold=threshold, cooldown_sec=cooldown)
    logger.warning("MCP discovery unavailable code=%s", reason)
    return _Connection([], None, reason=reason)


def current_health_event() -> AgentEvent | None:
    """Safe aggregate for the existing trace stream; no server identity or payload data."""
    payload = _HEALTH.get()
    if not payload:
        return None
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name="integration",
        data="",
        metadata={"kind": "integration_health", "integration_health": dict(payload)},
    )


@asynccontextmanager
async def open_mcp_tools(requested_ids: list[str] | None):
    """Подключиться к разрешённым серверам на время прогона и снять набор на выходе.

    Пустой список разрешённых — мгновенный no-op: обычный чат в сеть не ходит.
    """
    enabled, declared, timeout = _settings()
    servers = resolve_servers(declared, requested_ids) if enabled else []
    if not servers:
        yield ()
        return
    mode, threshold, cooldown = _resilience_settings()

    # ⚠️ БЕЗ `return_exceptions=True`: сдерживание уже внутри `_connect`, и второй слой
    # ловил бы ровно одно — отмену прогона, то есть превращал бы «пользователь ушёл» в
    # «продолжаем работать». Заодно двойное сдерживание делало ОБА слоя невидимыми для
    # мутации: снятие любого одного не краснило ни один тест.
    gathered = await asyncio.gather(
        *(
            _connect(server, timeout, mode=mode, threshold=threshold, cooldown=cooldown)
            for server in servers
        )
    )
    specs: list[ToolSpec] = []
    clients: list = []
    reasons: dict[str, int] = {}
    skipped_by_circuit = 0
    for item in gathered:
        if item.reason:
            reasons[item.reason] = reasons.get(item.reason, 0) + 1
        skipped_by_circuit += int(item.circuit_open)
        if item.client is not None:
            clients.append(item.client)
        specs.extend(item.specs)

    # A remote descriptor is never allowed to replace a built-in tool. Admission is
    # aggregate-only: rejected names and schemas stay out of trace and logs.
    from service.domain.capabilities.runtime import admit_mcp_specs

    admission = admit_mcp_specs(specs)
    specs = list(admission.accepted)
    for reason, count in admission.reasons.items():
        reasons[reason] = reasons.get(reason, 0) + count

    if len(specs) > MAX_TOOLS_TOTAL:
        logger.warning(
            "MCP: инструментов %d при потолке %d — лишние не выданы модели",
            len(specs),
            MAX_TOOLS_TOTAL,
        )
        specs = specs[:MAX_TOOLS_TOTAL]

    token = _SPECS.set(tuple(specs))
    health_token = _HEALTH.set(
        {
            "stage": "discovery",
            "mode": mode,
            "servers": len(servers),
            "reachable": sum(1 for item in gathered if item.client is not None),
            "tools": len(specs),
            "skipped": sum(reasons.values()),
            "circuit_open": skipped_by_circuit,
            "reasons": reasons,
        }
    )
    try:
        yield tuple(specs)
    finally:
        _SPECS.reset(token)
        _HEALTH.reset(health_token)
        for client in clients:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 — закрытие соединения ответ уже не меняет
                logger.debug("MCP: соединение закрылось с ошибкой")
