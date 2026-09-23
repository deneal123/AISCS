"""Compile the policy-approved canonical tool set for one provider."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .capabilities import (
    FunctionDialect,
    ProviderToolCapabilities,
    ToolChoiceMode,
)
from .schema import ProviderSchemaError, prepare_provider_schema, validate_function_name


class ProviderToolCompilationError(RuntimeError):
    """Bounded compatibility error used by failover and pinned-session handling."""

    def __init__(self, reason_code: str, *, invalid_count: int = 1) -> None:
        if reason_code not in {"tool_schema", "tool_choice", "provider_protocol"}:
            reason_code = "provider_protocol"
        self.reason_code = reason_code
        self.invalid_count = max(1, int(invalid_count))
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class CanonicalFunction:
    name: str
    description: str
    parameters: dict[str, Any]
    dynamic: bool = False


@dataclass(frozen=True, slots=True)
class NormalizedToolChoice:
    mode: ToolChoiceMode
    name: str | None = None


@dataclass(frozen=True, slots=True)
class CompiledToolSet:
    """Detached provider payload plus canonical metadata kept private to the run."""

    provider: str
    dialect: FunctionDialect
    functions: tuple[dict[str, Any], ...]
    choice: str | dict[str, Any]
    canonical_names: tuple[str, ...]
    max_calls_per_round: int | None

    def request_fields(self) -> dict[str, Any]:
        functions = [dict(function) for function in self.functions]
        if self.dialect is FunctionDialect.LEGACY_FUNCTIONS:
            return {"functions": functions, "function_call": self.choice}
        if self.dialect is FunctionDialect.OPENAI_TOOLS:
            return {
                "tools": [{"type": "function", "function": function} for function in functions],
                "tool_choice": self.choice,
            }
        return {}


def _is_dynamic_tool(tool: dict[str, Any]) -> bool:
    marker = tool.get("dynamic")
    if isinstance(marker, bool):
        return marker
    metadata = tool.get("metadata")
    if isinstance(metadata, dict):
        return bool(metadata.get("dynamic") or metadata.get("source") == "mcp")
    return False


def _canonical_function(tool: Any) -> CanonicalFunction:
    if not isinstance(tool, dict):
        raise ProviderToolCompilationError("tool_schema")
    function = tool.get("function") if tool.get("type") == "function" else tool
    if not isinstance(function, dict):
        raise ProviderToolCompilationError("tool_schema")
    name = function.get("name")
    description = function.get("description")
    parameters = function.get("parameters")
    if not isinstance(name, str) or not name:
        raise ProviderToolCompilationError("tool_schema")
    if not isinstance(description, str) or not description.strip():
        raise ProviderToolCompilationError("tool_schema")
    if not isinstance(parameters, dict):
        raise ProviderToolCompilationError("tool_schema")
    return CanonicalFunction(
        name=name,
        description=description,
        parameters=parameters,
        dynamic=_is_dynamic_tool(tool) or _is_dynamic_tool(function),
    )


def normalize_tool_choice(choice: Any) -> NormalizedToolChoice:
    if choice is None or choice == "auto":
        return NormalizedToolChoice(ToolChoiceMode.AUTO)
    if choice == "none":
        return NormalizedToolChoice(ToolChoiceMode.NONE)
    if choice == "required":
        return NormalizedToolChoice(ToolChoiceMode.REQUIRED)
    if isinstance(choice, dict):
        function = choice.get("function")
        name = function.get("name") if isinstance(function, dict) else choice.get("name")
        if isinstance(name, str) and name:
            return NormalizedToolChoice(ToolChoiceMode.FORCED, name)
    raise ProviderToolCompilationError("tool_choice")


def _compile_choice(
    normalized: NormalizedToolChoice,
    *,
    capabilities: ProviderToolCapabilities,
    names: tuple[str, ...],
) -> str | dict[str, Any]:
    mode = normalized.mode
    if mode is ToolChoiceMode.FORCED:
        if normalized.name not in names:
            raise ProviderToolCompilationError("tool_choice")
        if not capabilities.supports_choice(mode):
            raise ProviderToolCompilationError("tool_choice")
        if capabilities.dialect is FunctionDialect.LEGACY_FUNCTIONS:
            return {"name": normalized.name}
        return {"type": "function", "function": {"name": normalized.name}}
    if mode is ToolChoiceMode.REQUIRED and not capabilities.supports_choice(mode):
        # Required cannot be weakened to auto.  It is equivalent to a forced choice only
        # when exactly one eligible function exists.
        if len(names) == 1 and capabilities.supports_choice(ToolChoiceMode.FORCED):
            if capabilities.dialect is FunctionDialect.LEGACY_FUNCTIONS:
                return {"name": names[0]}
            return {"type": "function", "function": {"name": names[0]}}
        raise ProviderToolCompilationError("tool_choice")
    if not capabilities.supports_choice(mode):
        raise ProviderToolCompilationError("tool_choice")
    return mode.value


def compile_toolset(
    tools: Iterable[dict[str, Any]] | None,
    *,
    provider: str,
    capabilities: ProviderToolCapabilities,
    tool_choice: Any = None,
) -> CompiledToolSet:
    """Compile without changing policy eligibility or weakening tool schemas."""

    if not capabilities.supports_tools:
        if any(True for _ in tools or ()):
            raise ProviderToolCompilationError("provider_protocol")
        return CompiledToolSet(
            provider=provider,
            dialect=capabilities.dialect,
            functions=(),
            choice="none",
            canonical_names=(),
            max_calls_per_round=capabilities.max_calls_per_round,
        )
    canonical: list[CanonicalFunction] = []
    try:
        canonical = [_canonical_function(tool) for tool in tools or ()]
        names = tuple(
            validate_function_name(fn.name, capabilities.schema_profile) for fn in canonical
        )
        if len(set(names)) != len(names):
            raise ProviderToolCompilationError("tool_schema")
        compiled = tuple(
            {
                "name": fn.name,
                "description": fn.description,
                "parameters": prepare_provider_schema(
                    fn.parameters,
                    profile=capabilities.schema_profile,
                    dynamic=fn.dynamic and capabilities.fills_dynamic_descriptions,
                ),
            }
            for fn in canonical
        )
    except ProviderSchemaError as exc:
        raise ProviderToolCompilationError("tool_schema", invalid_count=exc.invalid_count) from exc
    normalized = normalize_tool_choice(tool_choice)
    choice = _compile_choice(normalized, capabilities=capabilities, names=names)
    return CompiledToolSet(
        provider=provider,
        dialect=capabilities.dialect,
        functions=compiled,
        choice=choice,
        canonical_names=names,
        max_calls_per_round=capabilities.max_calls_per_round,
    )


__all__ = [
    "CanonicalFunction",
    "CompiledToolSet",
    "NormalizedToolChoice",
    "ProviderToolCompilationError",
    "compile_toolset",
    "normalize_tool_choice",
]
