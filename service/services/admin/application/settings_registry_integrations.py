"""Workspace and MCP entries for the editable runtime-settings registry."""

from service.services.admin.application.settings_spec import SettingSpec, _s

INTEGRATION_SETTINGS: list[SettingSpec] = [
    _s(
        "agents.workspace_enabled",
        "Документы",
        "bool",
        "Файловая песочница",
        "Выдавать агенту инструменты изолированной рабочей среды.",
    ),
    _s(
        "agents.workspace_autocreate",
        "Документы",
        "bool",
        "Автосоздание песочницы",
        "Создавать рабочую среду для треда при первом обращении.",
    ),
    _s(
        "agents.workspace_timeout_sec",
        "Документы",
        "float",
        "Таймаут песочницы (сек)",
        "Лимит ожидания одной операции рабочей среды.",
        5.0,
        600.0,
    ),
    _s(
        "agents.mcp_enabled",
        "Документы",
        "bool",
        "Внешние MCP-серверы",
        "Разрешить модели инструменты объявленных MCP-серверов.",
    ),
    _s(
        "agents.mcp_servers",
        "Документы",
        "json",
        "MCP-серверы",
        "Административный список MCP-серверов и разрешённых инструментов.",
    ),
    _s(
        "agents.mcp_timeout_sec",
        "Документы",
        "float",
        "Таймаут MCP (сек)",
        "Лимит ожидания discovery и одного вызова MCP-инструмента.",
        1.0,
        120.0,
    ),
    _s(
        "agents.mcp_resilience_mode",
        "Документы",
        "str",
        "MCP resilience mode",
        "observe собирает сигналы; enforce учитывает открытый circuit breaker.",
    ),
    _s(
        "agents.mcp_circuit_failure_threshold",
        "Документы",
        "int",
        "Порог MCP circuit",
        "Число временных отказов discovery перед открытием circuit breaker.",
        1,
        20,
    ),
    _s(
        "agents.mcp_circuit_cooldown_sec",
        "Документы",
        "float",
        "Cooldown MCP circuit (сек)",
        "Сколько enforce пропускает сервер после открытия circuit breaker.",
        1.0,
        3600.0,
    ),
]
