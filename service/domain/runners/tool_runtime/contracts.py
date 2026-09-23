"""Closed internal contracts for tool normalization, execution, and accounting."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


class ToolCallStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TERMINAL = "terminal"
    REUSED = "reused"
    INVALID = "invalid"
    CANCELLED = "cancelled"


class ToolFailureCode(StrEnum):
    NONE = ""
    INVALID_JSON = "invalid_json"
    INVALID_ARGUMENTS = "invalid_arguments"
    UNKNOWN_TOOL = "unknown_tool"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    REMOTE = "remote"
    PROTOCOL = "protocol"
    POLICY = "policy"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


class BillingDisposition(StrEnum):
    ELIGIBLE = "eligible"
    NOT_BILLABLE = "not_billable"
    REUSED = "reused"
    INVALID = "invalid"
    FAILED = "failed"


class DedupReason(StrEnum):
    NONE = ""
    INFLIGHT = "inflight"
    COMPLETED = "completed"
    OBSERVED = "observed"


_STATUS_VALUES = frozenset(item.value for item in ToolCallStatus)
_FAILURE_VALUES = frozenset(item.value for item in ToolFailureCode)
_BILLING_VALUES = frozenset(item.value for item in BillingDisposition)
_DEDUP_VALUES = frozenset(item.value for item in DedupReason)


@dataclass(frozen=True, slots=True)
class ToolCallOutcome:
    """Result stored inside the run and projected safely to model/events.

    ``text`` is the model-facing tool result, not an exception string.  Diagnostics use
    only the closed fields below.  Positional fields preserve the pre-S23 constructor.
    """

    text: str
    status: str | ToolCallStatus
    duration_sec: float
    reused: bool = False
    dedup_observed: bool = False
    retryable: bool = False
    billable: bool = True
    dedup_reason: str | DedupReason = DedupReason.NONE
    failure_code: str | ToolFailureCode = ToolFailureCode.NONE
    billing_disposition: str | BillingDisposition = BillingDisposition.ELIGIBLE

    def __post_init__(self) -> None:
        status = str(self.status)
        failure = str(self.failure_code)
        dedup = str(self.dedup_reason)
        billing = str(self.billing_disposition)
        if status not in _STATUS_VALUES:
            raise ValueError(f"Unknown tool status: {status!r}")
        if failure not in _FAILURE_VALUES:
            raise ValueError(f"Unknown tool failure code: {failure!r}")
        if dedup not in _DEDUP_VALUES:
            raise ValueError(f"Unknown tool dedup reason: {dedup!r}")
        if billing not in _BILLING_VALUES:
            raise ValueError(f"Unknown billing disposition: {billing!r}")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "failure_code", failure)
        object.__setattr__(self, "dedup_reason", dedup)
        object.__setattr__(self, "billing_disposition", billing)
        object.__setattr__(self, "duration_sec", max(0.0, float(self.duration_sec or 0.0)))
        if self.reused:
            object.__setattr__(self, "billable", False)
            object.__setattr__(self, "billing_disposition", BillingDisposition.REUSED.value)
        elif status == ToolCallStatus.INVALID.value:
            object.__setattr__(self, "billable", False)
            object.__setattr__(self, "billing_disposition", BillingDisposition.INVALID.value)
        elif status in {ToolCallStatus.FAILED.value, ToolCallStatus.CANCELLED.value}:
            object.__setattr__(self, "billable", False)
            object.__setattr__(self, "billing_disposition", BillingDisposition.FAILED.value)
        elif not self.billable:
            object.__setattr__(self, "billing_disposition", BillingDisposition.NOT_BILLABLE.value)

    @property
    def succeeded(self) -> bool:
        return self.status == ToolCallStatus.SUCCEEDED.value

    @property
    def terminal(self) -> bool:
        return self.status == ToolCallStatus.TERMINAL.value

    @property
    def cacheable(self) -> bool:
        return self.succeeded or self.terminal

    @property
    def charged(self) -> bool:
        return self.billable and self.succeeded and not self.reused

    def as_reused(self, *, reason: DedupReason, duration_sec: float) -> ToolCallOutcome:
        return replace(
            self,
            status=ToolCallStatus.SUCCEEDED.value if self.succeeded else self.status,
            duration_sec=duration_sec,
            reused=True,
            billable=False,
            dedup_reason=reason.value,
            billing_disposition=BillingDisposition.REUSED.value,
        )

    def bounded_metadata(self) -> dict[str, Any]:
        return {
            "status": ToolCallStatus.REUSED.value if self.reused else self.status,
            "failure_code": self.failure_code,
            "retryable": self.retryable,
            "billing": self.billing_disposition,
            "dedup_reason": self.dedup_reason,
            "dedup_observed": self.dedup_observed,
        }


def invalid_arguments_outcome(code: ToolFailureCode) -> ToolCallOutcome:
    messages = {
        ToolFailureCode.INVALID_JSON: (
            "Аргументы инструмента не являются JSON-объектом. "
            "Исправь аргументы и вызови инструмент ещё раз."
        ),
        ToolFailureCode.INVALID_ARGUMENTS: (
            "Аргументы инструмента не соответствуют его контракту. "
            "Исправь аргументы и вызови инструмент ещё раз."
        ),
    }
    return ToolCallOutcome(
        messages.get(code, messages[ToolFailureCode.INVALID_ARGUMENTS]),
        ToolCallStatus.INVALID,
        0.0,
        retryable=True,
        billable=False,
        failure_code=code,
        billing_disposition=BillingDisposition.INVALID,
    )


def unavailable_tool_outcome() -> ToolCallOutcome:
    return ToolCallOutcome(
        "Запрошенный инструмент недоступен. Продолжи без него или выбери доступный.",
        ToolCallStatus.FAILED,
        0.0,
        retryable=False,
        billable=False,
        failure_code=ToolFailureCode.UNKNOWN_TOOL,
        billing_disposition=BillingDisposition.FAILED,
    )


__all__ = [
    "BillingDisposition",
    "DedupReason",
    "ToolCallOutcome",
    "ToolCallStatus",
    "ToolFailureCode",
    "invalid_arguments_outcome",
    "unavailable_tool_outcome",
]
