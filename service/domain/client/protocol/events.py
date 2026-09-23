"""Typed results at the provider boundary.

Provider SDK objects and the historical mutable usage projection are compatibility
details. Production orchestration consumes these envelopes instead: every accepted
call has an opaque identity, explicit provenance, and one ledger receipt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from service.domain.usage_ledger import UsageReceipt

from .session import ProviderRoundReceipt


class ProviderStreamEventKind(StrEnum):
    DELTA = "delta"
    REASONING = "reasoning"
    TOOL_CALLS = "tool_calls"
    COMPLETED = "completed"


@dataclass(slots=True)
class ProviderRoundState:
    """Private typed accumulator for one streamed provider attempt."""

    provider: str | None = None
    model: str | None = None
    prompt: int = 0
    completion: int = 0
    total: int = 0
    reasoning_tokens: int = 0
    reasoning: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None
    estimated: bool = False
    provider_fallback_reason: str | None = None

    def reset_attempt(self, *, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        self.prompt = 0
        self.completion = 0
        self.total = 0
        self.reasoning_tokens = 0
        self.reasoning = ""
        self.tool_calls.clear()
        self.finish_reason = None
        self.estimated = False

    def update(self, values: dict[str, Any]) -> None:
        """Test/provider-adapter helper with an allowlisted typed projection."""

        for name in (
            "provider",
            "model",
            "prompt",
            "completion",
            "total",
            "reasoning_tokens",
            "reasoning",
            "tool_calls",
            "finish_reason",
            "estimated",
            "provider_fallback_reason",
        ):
            if name not in values:
                continue
            value = values[name]
            if name in {"prompt", "completion", "total", "reasoning_tokens"}:
                value = max(0, int(value or 0))
            elif name == "tool_calls":
                value = [dict(item) for item in value or () if isinstance(item, dict)]
            elif name == "estimated":
                value = bool(value)
            elif value is not None:
                value = str(value)
            setattr(self, name, value)

    def usage(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "prompt": self.prompt,
            "completion": self.completion,
            "total": self.total or self.prompt + self.completion,
        }
        if self.provider:
            data["provider"] = self.provider
        if self.model:
            data["model"] = self.model
        if self.estimated:
            data["estimated"] = True
        return data

    def compatibility_payload(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.prompt or self.completion or self.total:
            data.update(self.usage())
        else:
            if self.provider:
                data["provider"] = self.provider
            if self.model:
                data["model"] = self.model
        for name in (
            "reasoning_tokens",
            "reasoning",
            "tool_calls",
            "finish_reason",
            "provider_fallback_reason",
        ):
            value = getattr(self, name)
            if value:
                data[name] = value
        return data


@dataclass(frozen=True, slots=True)
class ModelCallResult:
    """One completed non-stream model invocation."""

    response: Any
    call_id: str
    provider: str | None
    model: str | None
    finish_reason: str | None
    usage: UsageReceipt


@dataclass(frozen=True, slots=True)
class ProviderStreamEvent:
    """One typed event from a streamed provider round."""

    kind: ProviderStreamEventKind
    text: str = ""
    tool_calls: tuple[dict[str, Any], ...] = ()
    finish_reason: str | None = None
    call_id: str | None = None
    provider: str | None = None
    model: str | None = None
    round_receipt: ProviderRoundReceipt | None = None
    usage: UsageReceipt | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def delta(cls, text: str) -> ProviderStreamEvent:
        return cls(ProviderStreamEventKind.DELTA, text=str(text or ""))

    @classmethod
    def reasoning(cls, text: str, *, tokens: int = 0) -> ProviderStreamEvent:
        return cls(
            ProviderStreamEventKind.REASONING,
            text=str(text or ""),
            metadata={"tokens": max(0, int(tokens or 0))},
        )

    @classmethod
    def tool_calls_event(cls, calls: list[dict[str, Any]]) -> ProviderStreamEvent:
        return cls(
            ProviderStreamEventKind.TOOL_CALLS,
            tool_calls=tuple(dict(call) for call in calls if isinstance(call, dict)),
        )

    @classmethod
    def completed(
        cls,
        *,
        receipt: ProviderRoundReceipt | None,
        usage: UsageReceipt | None,
        finish_reason: str | None,
    ) -> ProviderStreamEvent:
        return cls(
            ProviderStreamEventKind.COMPLETED,
            finish_reason=finish_reason,
            call_id=(
                receipt.call_id if receipt is not None else (usage.receipt_id if usage else None)
            ),
            provider=(
                receipt.provider if receipt is not None else (usage.provider if usage else None)
            ),
            model=receipt.model if receipt is not None else (usage.model if usage else None),
            round_receipt=receipt,
            usage=usage,
        )


__all__ = [
    "ModelCallResult",
    "ProviderRoundState",
    "ProviderStreamEvent",
    "ProviderStreamEventKind",
]
