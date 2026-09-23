"""Compatibility facade for the unified provider schema compiler.

New runtime code compiles canonical tools through :mod:`service.domain.client.protocol`.
The old function-list API remains for the operational validation CLI and downstream
imports, but it no longer owns a second JSON Schema implementation.
"""

from __future__ import annotations

from typing import Any

from service.domain.client.protocol import (
    GIGACHAT_TOOL_CAPABILITIES,
    ProviderToolCompilationError,
    compile_toolset,
)


class GigaChatToolSchemaError(RuntimeError):
    reason_code = "tool_schema"

    def __init__(self, invalid_count: int = 1) -> None:
        self.invalid_count = max(1, int(invalid_count))
        super().__init__(self.reason_code)


def prepare_gigachat_functions(
    functions: list[dict[str, Any]] | None,
    *,
    fill_missing_descriptions: bool = True,
) -> list[dict[str, Any]]:
    """Validate/detach legacy function entries through the canonical compiler."""
    tools = [
        {
            "type": "function",
            "function": function,
            # Only dynamically discovered MCP functions may receive descriptions.
            "dynamic": bool(fill_missing_descriptions),
        }
        for function in functions or ()
    ]
    try:
        compiled = compile_toolset(
            tools,
            provider="gigachat",
            capabilities=GIGACHAT_TOOL_CAPABILITIES,
        )
    except ProviderToolCompilationError as exc:
        raise GigaChatToolSchemaError(exc.invalid_count) from None
    return [dict(function) for function in compiled.functions]


__all__ = ["GigaChatToolSchemaError", "prepare_gigachat_functions"]
