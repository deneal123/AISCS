"""Deadline-aware and cancellation-safe stage execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, TypeVar

import httpx

from service.domain.client.protocol import ModelCallResult
from service.domain.run_context import RunExecutionContext, require_current_execution
from service.domain.usage_ledger import UsageLedger, UsageReceipt
from service.shared import deadline

from .models import StageFailureCode, StageOutcome, StageReceipt, StageStatus

T = TypeVar("T")


@dataclass(slots=True)
class StageContext:
    execution: RunExecutionContext = field(default_factory=require_current_execution)
    receipts: list[StageReceipt] = field(default_factory=list)

    @property
    def usage(self) -> UsageLedger:
        return self.execution.usage

    def cancel(self) -> None:
        self.execution.cancel()

    @property
    def should_stop(self) -> bool:
        return self.execution.cancelled or deadline.must_finalize()

    def record(self, receipt: StageReceipt) -> None:
        self.receipts.append(receipt)
        if receipt.usage is not None:
            self.usage.record(receipt.usage)

    def bounded_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for receipt in self.receipts:
            key = receipt.status.value
            counts[key] = counts.get(key, 0) + 1
        return {"stage_count": len(self.receipts), **counts}


def _failure_code(exc: BaseException) -> StageFailureCode:
    code = str(getattr(exc, "reason_code", "") or "").strip().lower()
    aliases = {
        "unavailable": StageFailureCode.UNAVAILABLE,
        "timeout": StageFailureCode.TIMEOUT,
        "cancelled": StageFailureCode.CANCELLED,
        "invalid_response": StageFailureCode.INVALID_RESPONSE,
        "invalid_input": StageFailureCode.INVALID_INPUT,
        "transport": StageFailureCode.TRANSPORT,
        "remote": StageFailureCode.REMOTE,
        "protocol": StageFailureCode.PROTOCOL,
        "budget": StageFailureCode.BUDGET,
        "safety": StageFailureCode.SAFETY,
    }
    if code in aliases:
        return aliases[code]
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return StageFailureCode.TIMEOUT
    if isinstance(exc, httpx.TransportError):
        return StageFailureCode.TRANSPORT
    if isinstance(exc, asyncio.CancelledError):
        return StageFailureCode.CANCELLED
    return StageFailureCode.INTERNAL


class StageRuntime[T]:
    def __init__(
        self,
        context: StageContext,
        *,
        stage: str,
        timeout_sec: float,
        input_count: int = 0,
    ) -> None:
        self.context = context
        self.stage = stage
        self.timeout_sec = max(0.1, float(timeout_sec))
        self.input_count = max(0, int(input_count))

    async def run(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        usage_factory: Callable[[T], UsageReceipt | None] | None = None,
        output_count: Callable[[T], int] | None = None,
    ) -> StageOutcome[T]:
        if self.context.execution.cancelled:
            return self._stopped(StageStatus.CANCELLED, StageFailureCode.CANCELLED)
        if deadline.must_finalize():
            return self._stopped(StageStatus.DEADLINE, StageFailureCode.DEADLINE)
        started = perf_counter()
        try:
            value = await asyncio.wait_for(operation(), timeout=deadline.clamp(self.timeout_sec))
        except asyncio.CancelledError:
            receipt = self._receipt(started, StageStatus.CANCELLED, StageFailureCode.CANCELLED)
            self.context.record(receipt)
            raise
        except Exception as exc:  # noqa: BLE001
            code = _failure_code(exc)
            status = StageStatus.DEADLINE if deadline.must_finalize() else StageStatus.FAILED
            receipt = self._receipt(started, status, code)
            self.context.record(receipt)
            return StageOutcome(None, receipt)
        usage = usage_factory(value) if usage_factory else None
        count = output_count(value) if output_count else 1
        receipt = StageReceipt(
            stage=self.stage,
            status=StageStatus.SUCCEEDED,
            duration_ms=round((perf_counter() - started) * 1000),
            input_count=self.input_count,
            output_count=max(0, int(count)),
            usage=usage,
        )
        self.context.record(receipt)
        return StageOutcome(value, receipt)

    async def run_model(
        self,
        operation: Callable[[], Awaitable[ModelCallResult]],
        *,
        output_count: Callable[[Any], int] | None = None,
    ) -> StageOutcome[Any]:
        """Run one ledger-native model call and expose only its provider response.

        ``invoke_model_call`` records the usage receipt at the actual provider-call
        boundary.  Recording the same immutable receipt in the stage context is
        intentionally idempotent and associates operational stage status with the
        already-accounted call instead of creating a second billing source.
        """

        result = await self.run(
            operation,
            usage_factory=lambda value: value.usage,
            output_count=((lambda value: output_count(value.response)) if output_count else None),
        )
        if not result.ok or result.value is None:
            return StageOutcome(None, result.receipt, result.diagnostics)
        return StageOutcome(result.value.response, result.receipt, result.diagnostics)

    def _receipt(
        self,
        started: float,
        status: StageStatus,
        code: StageFailureCode,
    ) -> StageReceipt:
        return StageReceipt(
            stage=self.stage,
            status=status,
            failure_code=code,
            duration_ms=round((perf_counter() - started) * 1000),
            input_count=self.input_count,
        )

    def _stopped(self, status: StageStatus, code: StageFailureCode) -> StageOutcome[T]:
        receipt = StageReceipt(
            stage=self.stage,
            status=status,
            failure_code=code,
            input_count=self.input_count,
        )
        self.context.record(receipt)
        return StageOutcome(None, receipt)


__all__ = ["StageContext", "StageRuntime"]
