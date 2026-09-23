"""Инструмент чужого сервера → обычный `ToolSpec` нашего реестра.

🔴 ГЛАВНОЕ: MCP-инструмент НЕ получает своей машинерии. Он регистрируется тем же
`ToolSpec`, что и родной, и потому наследует гейт применимости, потолок результата,
кламп таймаута бюджетом прогона, тарификацию и отчёт об отказах — без единой своей строки
на каждый из этих механизмов. Ровно ради этого резолвер инструментов и делался общим.

⚠️ Вызов приходит АРГУМЕНТОМ, а не берётся из транспорта: адаптер ничего не знает про
сессии и сеть. Поэтому он проверяем целиком без сервера, а транспортный срез сведётся к
тому, чтобы подставить сюда настоящую корутину.

⚠️ Объект утиный, а не `FunctionTool` из SDK: `_tools_to_openai` и `_invoke_tool` работают
по атрибутам, и лишняя зависимость от SDK на живом пути нам не нужна — он там не исполняется.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from service.domain.capabilities.tool_spec import EFFECT_EXTERNAL_MUTATION, ToolSpec
from service.domain.runners.tool_runtime import ToolCallOutcome, ToolFailureCode
from service.infrastructure.mcp.naming import make_tool_name
from service.infrastructure.mcp.sanitize import sanitize_schema, tool_description, tool_result
from service.infrastructure.mcp.server_ref import ServerRef
from service.infrastructure.mcp.transport import McpError

logger = logging.getLogger(__name__)

# 🔴 ОДНА запись тарификации на весь MCP, а не по серверу и не по инструменту. Набор
# `BILLABLE_TOOLS` сверяется с прайсом backend'а офлайн-гейтом парити: запись на сервер
# превращала бы КАЖДЫЙ новый сервер в согласованный релиз двух репозиториев.
BILLING_NAME = "mcp_tool"

# Потолок числа инструментов с одного сервера. Манифест разговорчивого сервера иначе вытеснит
# из бюджета контекста файл пользователя: схемы уезжают в КАЖДОМ запросе.
MAX_TOOLS_PER_SERVER = 20

CallTool = Callable[[str, str], Awaitable[str]]


@dataclass(slots=True)
class McpTool:
    """Утиный двойник `FunctionTool`: раннеру нужны имя, описание, схема и вызов."""

    name: str
    description: str
    params_json_schema: dict
    on_invoke_tool: Callable[[Any, str], Awaitable[str | ToolCallOutcome]]
    source: str = "mcp"


def _bind(
    server: ServerRef, remote_name: str, call: CallTool
) -> Callable[[Any, str], Awaitable[str | ToolCallOutcome]]:
    async def _invoke(_ctx: Any, arguments: str) -> str | ToolCallOutcome:
        try:
            raw = await call(remote_name, arguments or "{}")
        except McpError as exc:
            failure = {
                "timeout": ToolFailureCode.TIMEOUT,
                "transport": ToolFailureCode.TRANSPORT,
                "remote": ToolFailureCode.REMOTE,
                "protocol": ToolFailureCode.PROTOCOL,
                "circuit_open": ToolFailureCode.UNAVAILABLE,
            }.get(str(exc.code), ToolFailureCode.INTERNAL)
            logger.warning("MCP invocation failed code=%s", failure.value)
            return ToolCallOutcome(
                "Внешний инструмент временно не дал безопасного результата. Продолжи без него.",
                "failed",
                0.0,
                retryable=bool(exc.retryable),
                billable=False,
                failure_code=failure,
            )
        except Exception:  # noqa: BLE001
            logger.warning("MCP invocation failed code=internal")
            return ToolCallOutcome(
                "Внешний инструмент завершился безопасно обработанной ошибкой.",
                "failed",
                0.0,
                retryable=False,
                billable=False,
                failure_code=ToolFailureCode.INTERNAL,
            )
        return tool_result(raw)

    return _invoke


def mcp_tool_specs(server: ServerRef, descriptors: list[dict], call: CallTool) -> list[ToolSpec]:
    """Описания инструментов сервера → спеки нашего реестра.

    Инструмент пропускается, если имя непригодно или он не в белом списке сервера. Пропуск
    ГРОМКИЙ: молча укоротившийся список выглядит как «у сервера столько и есть».
    """
    allowed = set(server.allowed_tools)
    specs: list[ToolSpec] = []
    for item in descriptors or ():
        if len(specs) >= MAX_TOOLS_PER_SERVER:
            logger.warning(
                "MCP %s: инструментов больше %d — остальные не выданы модели",
                server.id,
                MAX_TOOLS_PER_SERVER,
            )
            break
        remote = str((item or {}).get("name") or "").strip()
        if allowed and remote not in allowed:
            continue
        name = make_tool_name(server.id, remote)
        if not name:
            logger.warning(
                "MCP %s: инструмент %r без пригодного имени — пропущен", server.id, remote
            )
            continue
        specs.append(
            ToolSpec(
                name=name,
                tool=McpTool(
                    name=name,
                    description=tool_description(server.id, (item or {}).get("description") or ""),
                    params_json_schema=sanitize_schema((item or {}).get("input_schema")),
                    on_invoke_tool=_bind(server, remote, call),
                ),
                billing_name=BILLING_NAME,
                source="mcp",
                effect=EFFECT_EXTERNAL_MUTATION,
            )
        )
    return specs
