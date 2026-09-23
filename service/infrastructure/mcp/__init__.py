"""Клиент MCP: чужие инструменты как свои, но с явной границей доверия.

Слои: именование и обрамление недоверенного контента (`naming`, `sanitize`), разрешение
объявленных серверов (`server_ref`), превращение чужого инструмента в наш `ToolSpec`
(`adapter`), сессия JSON-RPC (`transport`) и набор инструментов одного прогона (`runtime`).
Безопасная половина сделана ПЕРВОЙ и не зависит от транспорта: цена ошибки именно в ней.

⚠️ ПОЧЕМУ НЕ `agents.mcp` ИЗ SDK. Тот подключается через `Agent(mcp_servers=…)`, что
исполняется только на SDK-пути, а живой путь для всех четырёх рабочих провайдеров —
`chat_run`. Получилась бы способность, работающая в тестах и на нативном OpenAI, и больше
нигде. Свой клиент отдаёт объекты ФОРМЫ `FunctionTool`, а `_tools_to_openai` и `_invoke_tool`
работают по утиной типизации — значит MCP-инструмент попадает в тот же реестр, гейт, лимиты,
биллинг и отчёт об отказах, что и родной.
"""

from .adapter import BILLING_NAME, McpTool, mcp_tool_specs
from .naming import make_tool_name, parse_tool_name
from .runtime import current_health_event, current_specs, current_tools, open_mcp_tools
from .sanitize import sanitize_schema, tool_description, tool_result, wrap_untrusted
from .server_ref import ServerRef, resolve_servers
from .transport import McpError, McpSession, open_session

__all__ = [
    "BILLING_NAME",
    "McpError",
    "McpSession",
    "McpTool",
    "ServerRef",
    "current_specs",
    "current_tools",
    "current_health_event",
    "mcp_tool_specs",
    "make_tool_name",
    "open_mcp_tools",
    "open_session",
    "parse_tool_name",
    "resolve_servers",
    "sanitize_schema",
    "tool_description",
    "tool_result",
    "wrap_untrusted",
]
