"""Typed provider capabilities used while compiling a tool-enabled round."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FunctionDialect(StrEnum):
    """Wire representation accepted by a provider."""

    OPENAI_TOOLS = "openai_tools"
    LEGACY_FUNCTIONS = "legacy_functions"
    NONE = "none"


class ToolChoiceMode(StrEnum):
    """Closed set of tool-choice semantics understood by the execution core."""

    AUTO = "auto"
    NONE = "none"
    REQUIRED = "required"
    FORCED = "forced"


class SchemaProfile(StrEnum):
    """Provider schema profile, independent from its function wire dialect."""

    OPENAI = "openai"
    GIGACHAT = "gigachat"


@dataclass(frozen=True, slots=True)
class ProviderToolCapabilities:
    """All tool-protocol decisions for one provider.

    The value is immutable and belongs to :class:`ProviderSpec`.  It replaces feature
    booleans spread across streaming, response normalization, and provider modules.
    """

    dialect: FunctionDialect = FunctionDialect.OPENAI_TOOLS
    schema_profile: SchemaProfile = SchemaProfile.OPENAI
    supported_choices: frozenset[ToolChoiceMode] = frozenset(
        {
            ToolChoiceMode.AUTO,
            ToolChoiceMode.NONE,
            ToolChoiceMode.REQUIRED,
            ToolChoiceMode.FORCED,
        }
    )
    max_calls_per_round: int | None = None
    supports_parallel_calls: bool = True
    streams_usage_on_request: bool = True
    returns_stream_usage_without_request: bool = False
    supports_private_round_state: bool = False
    requires_object_arguments: bool = False
    requires_json_object_results: bool = False
    fills_dynamic_descriptions: bool = False

    def __post_init__(self) -> None:
        if self.max_calls_per_round is not None and self.max_calls_per_round < 1:
            raise ValueError("max_calls_per_round must be positive")
        if self.dialect is FunctionDialect.NONE and self.supported_choices:
            raise ValueError("tool-less providers cannot advertise tool choices")
        if self.supports_parallel_calls and self.max_calls_per_round == 1:
            raise ValueError("parallel calls conflict with max_calls_per_round=1")

    @property
    def supports_tools(self) -> bool:
        return self.dialect is not FunctionDialect.NONE

    def supports_choice(self, mode: ToolChoiceMode) -> bool:
        return mode in self.supported_choices


OPENAI_TOOL_CAPABILITIES = ProviderToolCapabilities()

GIGACHAT_TOOL_CAPABILITIES = ProviderToolCapabilities(
    dialect=FunctionDialect.LEGACY_FUNCTIONS,
    schema_profile=SchemaProfile.GIGACHAT,
    supported_choices=frozenset({ToolChoiceMode.AUTO, ToolChoiceMode.NONE, ToolChoiceMode.FORCED}),
    max_calls_per_round=1,
    supports_parallel_calls=False,
    streams_usage_on_request=False,
    returns_stream_usage_without_request=True,
    supports_private_round_state=True,
    requires_object_arguments=True,
    requires_json_object_results=True,
    fills_dynamic_descriptions=True,
)


__all__ = [
    "FunctionDialect",
    "GIGACHAT_TOOL_CAPABILITIES",
    "OPENAI_TOOL_CAPABILITIES",
    "ProviderToolCapabilities",
    "SchemaProfile",
    "ToolChoiceMode",
]
