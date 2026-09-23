"""Provider-neutral execution protocol for model and tool rounds.

The public client facade still accepts OpenAI-shaped messages and tools.  This package
keeps provider differences explicit and private so policy, tool execution, events, and
billing do not depend on wire dialects.
"""

from .capabilities import (
    GIGACHAT_TOOL_CAPABILITIES,
    OPENAI_TOOL_CAPABILITIES,
    FunctionDialect,
    ProviderToolCapabilities,
    SchemaProfile,
    ToolChoiceMode,
)
from .compiler import CompiledToolSet, ProviderToolCompilationError, compile_toolset
from .events import (
    ModelCallResult,
    ProviderRoundState,
    ProviderStreamEvent,
    ProviderStreamEventKind,
)
from .failures import (
    ProviderFailure,
    ProviderFailureCode,
    ProviderProtocolError,
    classify_provider_failure,
    safe_failure_metadata,
)
from .session import PinSource, ProviderRoundReceipt, ProviderRunSession

__all__ = [
    "CompiledToolSet",
    "FunctionDialect",
    "GIGACHAT_TOOL_CAPABILITIES",
    "ModelCallResult",
    "ProviderRoundState",
    "OPENAI_TOOL_CAPABILITIES",
    "PinSource",
    "ProviderFailure",
    "ProviderFailureCode",
    "ProviderProtocolError",
    "ProviderStreamEvent",
    "ProviderStreamEventKind",
    "ProviderRoundReceipt",
    "ProviderRunSession",
    "ProviderToolCapabilities",
    "ProviderToolCompilationError",
    "SchemaProfile",
    "ToolChoiceMode",
    "classify_provider_failure",
    "compile_toolset",
    "safe_failure_metadata",
]
