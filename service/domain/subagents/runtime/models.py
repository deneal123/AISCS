"""Closed stage contracts shared by research, query, and audio flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar

from service.domain.usage_ledger import UsageReceipt

T = TypeVar("T")


class StageStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEADLINE = "deadline"


class StageFailureCode(StrEnum):
    NONE = ""
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    DEADLINE = "deadline"
    CANCELLED = "cancelled"
    INVALID_RESPONSE = "invalid_response"
    INVALID_INPUT = "invalid_input"
    TRANSPORT = "transport"
    REMOTE = "remote"
    PROTOCOL = "protocol"
    BUDGET = "budget"
    SAFETY = "safety"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class StageReceipt:
    stage: str
    status: StageStatus
    failure_code: StageFailureCode = StageFailureCode.NONE
    duration_ms: int = 0
    input_count: int = 0
    output_count: int = 0
    usage: UsageReceipt | None = None

    def bounded_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "stage": self.stage,
            "status": self.status.value,
            "duration_ms": max(0, self.duration_ms),
            "input_count": max(0, self.input_count),
            "output_count": max(0, self.output_count),
        }
        if self.failure_code is not StageFailureCode.NONE:
            data["failure_code"] = self.failure_code.value
        if self.usage is not None:
            data["usage_recorded"] = True
        return data


@dataclass(frozen=True, slots=True)
class StageOutcome[T]:
    value: T | None
    receipt: StageReceipt
    diagnostics: dict[str, int | str | bool] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.receipt.status in {StageStatus.SUCCEEDED, StageStatus.PARTIAL}

    @property
    def partial(self) -> bool:
        return self.receipt.status is StageStatus.PARTIAL

    @classmethod
    def success(
        cls,
        value: T,
        *,
        stage: str,
        duration_ms: int = 0,
        input_count: int = 0,
        output_count: int = 0,
        usage: UsageReceipt | None = None,
    ) -> StageOutcome[T]:
        return cls(
            value,
            StageReceipt(
                stage=stage,
                status=StageStatus.SUCCEEDED,
                duration_ms=duration_ms,
                input_count=input_count,
                output_count=output_count,
                usage=usage,
            ),
        )

    @classmethod
    def failure(
        cls,
        *,
        stage: str,
        status: StageStatus = StageStatus.FAILED,
        code: StageFailureCode = StageFailureCode.INTERNAL,
        duration_ms: int = 0,
        input_count: int = 0,
    ) -> StageOutcome[T]:
        return cls(
            None,
            StageReceipt(
                stage=stage,
                status=status,
                failure_code=code,
                duration_ms=duration_ms,
                input_count=input_count,
            ),
        )


__all__ = ["StageFailureCode", "StageOutcome", "StageReceipt", "StageStatus"]
