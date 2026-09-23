"""Policy metadata for native workspace tools.

The executable functions live in :mod:`workspace_tools`; this module owns only the
capability/billing/disclosure contract. Keeping those concerns separate prevents a
schema-only change from being mixed with workspace I/O behavior.
"""

from __future__ import annotations

from collections.abc import Iterable

from agents import FunctionTool

from service.domain.capabilities.tool_spec import (
    EFFECT_READ_ONLY,
    EFFECT_WORKSPACE_MUTATION,
    GROUNDING_WORKSPACE,
    ToolSpec,
)

BILLING_NAME = "workspace_tool"
ENABLED_FIELD = "workspace_enabled"
CONTEXT_ATTR = "workspace_tools_enabled"

_DEFAULT_HINT = "работать с файлами песочницы"
_SELECTOR_HINTS = {
    "ws_list": "показать дерево файлов песочницы",
    "ws_read": "прочитать файл из песочницы",
    "ws_write": "создать или перезаписать файл в песочнице",
    "ws_edit": "внести точечную правку в файл песочницы",
    "ws_grep": "найти текст или код по файлам песочницы",
    "ws_run": "запустить команду в изолированной песочнице",
    "ws_history": "посмотреть историю изменений файлов",
    "ws_diff": "посмотреть изменения относительно исходного состояния",
    "ws_revert": "откатить файл к предыдущей версии",
    "ws_issues": "прочитать активные задачи рабочей области",
    "ws_issue_update": "обновить статус задачи рабочей области",
}
_MUTATIONS = frozenset({"ws_write", "ws_edit", "ws_run", "ws_revert", "ws_issue_update"})


def build_workspace_specs(
    tools: Iterable[FunctionTool],
    *,
    result_limits: dict[str, int] | None = None,
) -> list[ToolSpec]:
    """Bind executable tools to the shared workspace policy contract."""
    limits = result_limits or {}
    specs: list[ToolSpec] = []
    for tool in tools:
        result_limit = limits.get(tool.name)
        specs.append(
            ToolSpec(
                name=tool.name,
                tool=tool,
                requires_context_attr=CONTEXT_ATTR,
                billing_name=BILLING_NAME,
                enabled_field=ENABLED_FIELD,
                source="workspace",
                selector_hint=_SELECTOR_HINTS.get(tool.name, _DEFAULT_HINT),
                effect=(EFFECT_WORKSPACE_MUTATION if tool.name in _MUTATIONS else EFFECT_READ_ONLY),
                concurrency_group=("workspace" if tool.name in _MUTATIONS else None),
                grounding_roles=frozenset({GROUNDING_WORKSPACE}),
                **({"result_limit_chars": result_limit} if result_limit is not None else {}),
            )
        )
    return specs
