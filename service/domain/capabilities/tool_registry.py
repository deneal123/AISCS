"""Tool policy facade backed by the static catalog and one run-local MCP overlay."""

from __future__ import annotations

from typing import Any

from .compiler import compile_static_catalog
from .runtime import admit_mcp_specs, get_static_catalog
from .sources import AGENT_SOURCES, TOOL_SOURCES, WORKFLOW_SOURCES
from .tool_spec import (
    CATALOG_UNKNOWN,
    DEFAULT_RESULT_LIMIT,
    DEFAULT_TOOL_TIMEOUT_SEC,
    DISABLED_BY_CONFIG,
    MISSING_DATA,
    MODEL_NO_TOOL_SUPPORT,
    NEEDS_CONFIRMATION,
    Omission,
    ToolSet,
    ToolSpec,
)

# Mutable compatibility seam for older synthetic registration tests only.
_TOOL_SOURCES = TOOL_SOURCES


def _execution():
    from service.domain.run_context import current_execution

    return current_execution()


def _discover() -> dict[str, ToolSpec]:
    if _TOOL_SOURCES != TOOL_SOURCES:
        catalog = compile_static_catalog(
            agent_sources=AGENT_SOURCES,
            workflow_sources=WORKFLOW_SOURCES,
            tool_sources=_TOOL_SOURCES,
            billable_contract=None,
        )
        return dict(catalog.native_tools)
    return dict(get_static_catalog().native_tools)


def _run_scoped_specs() -> tuple[ToolSpec, ...]:
    from service.infrastructure.mcp.runtime import current_specs

    return current_specs()


def tool_specs() -> dict[str, ToolSpec]:
    if _TOOL_SOURCES != TOOL_SOURCES:
        return _discover()
    execution = _execution()
    if execution is not None:
        found = dict(execution.capabilities.tools)
        # Compatibility for direct callers that open the MCP context after their test
        # run scope. Production discovers MCP before constructing RunExecutionContext,
        # so its immutable overlay remains the sole source there.
        ambient = _run_scoped_specs()
        if ambient:
            admitted = admit_mcp_specs(ambient)
            found.update(
                {
                    spec.name: spec
                    for spec in admitted.accepted
                    if spec.name not in execution.capabilities.static.native_tools
                }
            )
        return found
    found = _discover()
    admitted = admit_mcp_specs(_run_scoped_specs())
    found.update({spec.name: spec for spec in admitted.accepted})
    return found


def get_tool_spec(name: str) -> ToolSpec | None:
    if _TOOL_SOURCES != TOOL_SOURCES:
        return tool_specs().get(str(name or "").strip())
    execution = _execution()
    if execution is not None:
        return execution.capabilities.tool(name)
    return tool_specs().get(str(name or "").strip())


def tool_billing_names() -> dict[str, str]:
    return {spec.name: spec.billing_name for spec in tool_specs().values() if spec.billing_name}


def tool_result_limit(name: str) -> int | None:
    spec = get_tool_spec(name)
    return spec.result_limit_chars if spec else DEFAULT_RESULT_LIMIT


def tool_timeout(name: str) -> float:
    spec = get_tool_spec(name)
    return spec.default_timeout_sec if spec else DEFAULT_TOOL_TIMEOUT_SEC


def tool_dedup_safe(name: str) -> bool:
    spec = get_tool_spec(name)
    return bool(spec and spec.dedup_safe)


def tool_concurrency_group(name: str) -> str | None:
    spec = get_tool_spec(name)
    return str(spec.concurrency_group) if spec and spec.concurrency_group else None


def tool_grounding_roles(name: str) -> frozenset[str]:
    spec = get_tool_spec(name)
    return spec.grounding_roles if spec else frozenset()


def resolve_toolset(
    tools: list, context: Any | None, *, model_supports: bool | None = True
) -> ToolSet:
    """Apply model, settings, context, and confirmation gates to one run snapshot."""

    if not tools:
        return _capture_omissions(ToolSet())
    specs = tool_specs()
    present = {str(getattr(tool, "name", "") or "") for tool in tools}
    tools = [
        *tools,
        *(
            spec.tool
            for spec in specs.values()
            if spec.source == "mcp" and spec.name not in present
        ),
    ]
    names = [str(getattr(tool, "name", "") or "") or "<без имени>" for tool in tools]
    if model_supports is None:
        return _capture_omissions(
            ToolSet(
                omissions=[
                    Omission(name, CATALOG_UNKNOWN, "каталог моделей недоступен") for name in names
                ]
            )
        )
    if not model_supports:
        return _capture_omissions(
            ToolSet(omissions=[Omission(name, MODEL_NO_TOOL_SUPPORT) for name in names])
        )

    kept: list = []
    omitted: list[Omission] = []
    for tool, name in zip(tools, names, strict=True):
        spec = specs.get(name)
        if spec and spec.enabled_field and not _flag_enabled(spec.enabled_field):
            omitted.append(Omission(name, DISABLED_BY_CONFIG, spec.enabled_field))
            continue
        required = spec.requires_context_attr if spec else None
        if required:
            from service.domain.run_context import policy_flag

            if not policy_flag(context, required):
                reason = NEEDS_CONFIRMATION if spec.confirm_by_default else MISSING_DATA
                omitted.append(Omission(name, reason, required))
                continue
        kept.append(tool)
    return _capture_omissions(ToolSet(tools=kept, omissions=omitted))


def _capture_omissions(toolset: ToolSet) -> ToolSet:
    execution = _execution()
    if execution is not None:
        execution.capabilities = execution.capabilities.with_omissions(tuple(toolset.omissions))
    return toolset


def _flag_enabled(field: str) -> bool:
    execution = _execution()
    if execution is not None:
        return execution.capabilities.policy.flag(field)

    from service.settings import config
    from service.shared.agent_settings import runtime_settings

    default = getattr(config.agents, field, True)
    return bool(runtime_settings.get_agents(field, default))


__all__ = [
    "get_tool_spec",
    "resolve_toolset",
    "tool_billing_names",
    "tool_concurrency_group",
    "tool_dedup_safe",
    "tool_grounding_roles",
    "tool_result_limit",
    "tool_specs",
    "tool_timeout",
]
