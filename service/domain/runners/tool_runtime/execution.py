"""Concurrent normalize/validate/deduplicate/invoke kernel for tool calls."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Any

from .arguments import ArgumentIssueCode, ToolArgumentError, parse_and_validate_arguments
from .contracts import (
    DedupReason,
    ToolCallOutcome,
    ToolCallStatus,
    ToolFailureCode,
    invalid_arguments_outcome,
    unavailable_tool_outcome,
)

Invoker = Callable[[Any, Any, str], Awaitable[ToolCallOutcome | str]]


@dataclass(frozen=True, slots=True)
class NormalizedToolCall:
    position: int
    call_id: str
    name: str
    raw_arguments: Any


@dataclass(frozen=True, slots=True)
class ValidatedToolCall:
    position: int
    call_id: str
    name: str
    arguments: dict[str, Any]
    invoke_arguments: str
    canonical_arguments: str
    cache_key: str


@dataclass(slots=True)
class ToolCallCache:
    """Run-scoped completed and in-flight outcomes for explicitly safe tools only."""

    completed: dict[str, ToolCallOutcome] = field(default_factory=dict)
    in_flight: dict[str, asyncio.Task[ToolCallOutcome] | None] = field(default_factory=dict)

    def clear_retryable(self) -> None:
        self.completed = {
            key: outcome for key, outcome in self.completed.items() if not outcome.retryable
        }

    def bounded_size(self) -> dict[str, int]:
        return {"completed": len(self.completed), "inflight": len(self.in_flight)}


def normalize_tool_call(call: Any, position: int) -> NormalizedToolCall | None:
    if not isinstance(call, dict):
        return None
    name = call.get("name")
    call_id = call.get("id")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(call_id, str) or not call_id.strip():
        call_id = f"call_invalid_{position}"
    return NormalizedToolCall(
        position=position,
        call_id=call_id[:256],
        name=name.strip()[:256],
        raw_arguments=call.get("arguments", "{}"),
    )


def _schema_for(tool: Any) -> dict[str, Any] | None:
    schema = getattr(tool, "params_json_schema", None)
    if isinstance(schema, dict):
        return schema
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("parameters"), dict):
            return function["parameters"]
    return None


def validate_tool_call(call: NormalizedToolCall, tool: Any) -> ValidatedToolCall:
    schema = _schema_for(tool)
    if schema is None:
        # Compatibility for internal test doubles. Production tools always have a
        # schema; accepting a JSON object here does not weaken a declared contract.
        parsed, canonical = parse_and_validate_arguments(
            call.raw_arguments,
            {"type": "object", "properties": {}, "additionalProperties": True},
        )
    else:
        parsed, canonical = parse_and_validate_arguments(call.raw_arguments, schema)
    return ValidatedToolCall(
        position=call.position,
        call_id=call.call_id,
        name=call.name,
        arguments=parsed,
        invoke_arguments=(call.raw_arguments if isinstance(call.raw_arguments, str) else canonical),
        canonical_arguments=canonical,
        cache_key=f"{call.name}\x1f{canonical}",
    )


def _validation_failure(exc: ToolArgumentError) -> ToolCallOutcome:
    invalid_json = any(
        issue.code in {ArgumentIssueCode.INVALID_JSON, ArgumentIssueCode.EXPECTED_OBJECT}
        for issue in exc.issues
    )
    return invalid_arguments_outcome(
        ToolFailureCode.INVALID_JSON if invalid_json else ToolFailureCode.INVALID_ARGUMENTS
    )


@dataclass(slots=True)
class _ExecutionContext:
    tool_index: dict[str, Any]
    tool_context: Any
    invoker: Invoker
    cache: ToolCallCache | None
    dedup_safe: Callable[[str], bool] | None
    concurrency_group: Callable[[str], str | None] | None
    dedup_mode: str
    gate: asyncio.Semaphore
    group_locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def safe_to_deduplicate(self, name: str) -> bool:
        return bool(self.dedup_safe and self.dedup_safe(name))

    async def invoke(
        self, call: ValidatedToolCall, tool: Any, *, observed: bool
    ) -> ToolCallOutcome:
        started = perf_counter()
        group = self.concurrency_group(call.name) if self.concurrency_group else None

        async def _invoke() -> ToolCallOutcome | str:
            async with self.gate:
                return await self.invoker(tool, self.tool_context, call.invoke_arguments)

        if group:
            lock = self.group_locks.setdefault(group, asyncio.Lock())
            async with lock:
                result = await _invoke()
        else:
            result = await _invoke()
        duration = perf_counter() - started
        if isinstance(result, ToolCallOutcome):
            return replace(
                result,
                duration_sec=duration,
                dedup_observed=observed,
                dedup_reason=(DedupReason.OBSERVED.value if observed else result.dedup_reason),
            )
        return ToolCallOutcome(
            str(result),
            ToolCallStatus.SUCCEEDED,
            duration,
            dedup_observed=observed,
            dedup_reason=DedupReason.OBSERVED if observed else DedupReason.NONE,
        )

    async def run(self, call: Any, position: int) -> ToolCallOutcome:
        from service.domain.run_context import require_current_execution

        run_execution = require_current_execution()
        if run_execution.cancelled:
            return ToolCallOutcome(
                "Операция отменена.",
                ToolCallStatus.CANCELLED,
                0.0,
                billable=False,
                failure_code=ToolFailureCode.CANCELLED,
            )
        normalized = normalize_tool_call(call, position)
        if normalized is None:
            return invalid_arguments_outcome(ToolFailureCode.INVALID_ARGUMENTS)
        tool = self.tool_index.get(normalized.name)
        if tool is None:
            return unavailable_tool_outcome()
        try:
            validated = validate_tool_call(normalized, tool)
        except ToolArgumentError as exc:
            return _validation_failure(exc)
        safe = self.safe_to_deduplicate(validated.name)
        if self.cache is None or not safe or self.dedup_mode == "off":
            return await self.invoke(validated, tool, observed=False)
        if self.dedup_mode == "enforce":
            return await self._run_enforced(validated, tool)
        return await self._run_observed(validated, tool)

    async def _run_enforced(self, call: ValidatedToolCall, tool: Any) -> ToolCallOutcome:
        assert self.cache is not None
        started = perf_counter()
        cached = self.cache.completed.get(call.cache_key)
        if cached is not None:
            return cached.as_reused(
                reason=DedupReason.COMPLETED,
                duration_sec=perf_counter() - started,
            )
        pending = self.cache.in_flight.get(call.cache_key)
        if pending is not None:
            outcome = await asyncio.shield(pending)
            return outcome.as_reused(
                reason=DedupReason.INFLIGHT,
                duration_sec=perf_counter() - started,
            )
        pending = asyncio.create_task(self.invoke(call, tool, observed=False))
        self.cache.in_flight[call.cache_key] = pending
        try:
            outcome = await pending
        finally:
            self.cache.in_flight.pop(call.cache_key, None)
        if outcome.cacheable and not outcome.retryable:
            self.cache.completed[call.cache_key] = outcome
        elif outcome.succeeded or outcome.terminal:
            self.cache.completed[call.cache_key] = outcome
        return outcome

    async def _run_observed(self, call: ValidatedToolCall, tool: Any) -> ToolCallOutcome:
        assert self.cache is not None
        observed = bool(
            self.cache.completed.get(call.cache_key) is not None
            or call.cache_key in self.cache.in_flight
        )
        # An observe marker must not make another call await this invocation.
        self.cache.in_flight[call.cache_key] = None
        try:
            outcome = await self.invoke(call, tool, observed=observed)
        finally:
            self.cache.in_flight.pop(call.cache_key, None)
        if outcome.cacheable and not outcome.retryable:
            self.cache.completed[call.cache_key] = outcome
        elif outcome.succeeded or outcome.terminal:
            self.cache.completed[call.cache_key] = outcome
        return outcome


async def execute_tool_calls(
    tool_calls: list[dict],
    tool_index: dict,
    tool_context: Any,
    *,
    concurrency: int,
    invoker: Invoker,
    cache: ToolCallCache | None = None,
    dedup_safe: Callable[[str], bool] | None = None,
    concurrency_group: Callable[[str], str | None] | None = None,
    dedup_mode: str = "enforce",
) -> list[ToolCallOutcome]:
    """Execute calls concurrently and preserve the model's original order."""

    if dedup_mode not in {"off", "observe", "enforce"}:
        dedup_mode = "off"
    execution = _ExecutionContext(
        tool_index=tool_index,
        tool_context=tool_context,
        invoker=invoker,
        cache=cache,
        dedup_safe=dedup_safe,
        concurrency_group=concurrency_group,
        dedup_mode=dedup_mode,
        gate=asyncio.Semaphore(max(1, int(concurrency))),
    )
    return await asyncio.gather(
        *(execution.run(call, position) for position, call in enumerate(tool_calls))
    )


__all__ = [
    "NormalizedToolCall",
    "ToolCallCache",
    "ValidatedToolCall",
    "execute_tool_calls",
    "normalize_tool_call",
    "validate_tool_call",
]
