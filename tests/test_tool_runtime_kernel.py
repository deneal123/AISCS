from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from service.domain.runners.tool_runtime import (
    DedupReason,
    ToolCallCache,
    ToolCallOutcome,
    ToolCallStatus,
    ToolFailureCode,
    execute_tool_calls,
)


def _tool() -> SimpleNamespace:
    return SimpleNamespace(
        params_json_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "options": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["brief", "full"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["mode"],
                    "additionalProperties": False,
                },
            },
            "required": ["path", "options"],
            "additionalProperties": False,
        }
    )


@pytest.mark.asyncio
async def test_invalid_arguments_never_invoke_or_bill_and_do_not_echo_values() -> None:
    invoked = 0

    async def invoke(tool, context, arguments):
        nonlocal invoked
        invoked += 1
        return "unexpected"

    marker = "PRIVATE-ARGUMENT-MARKER"
    outcomes = await execute_tool_calls(
        [
            {"id": "one", "name": "read", "arguments": "not-json"},
            {
                "id": "two",
                "name": "read",
                "arguments": {"path": marker, "options": {"mode": "invalid"}},
            },
        ],
        {"read": _tool()},
        object(),
        concurrency=2,
        invoker=invoke,
    )

    assert invoked == 0
    assert [item.status for item in outcomes] == ["invalid", "invalid"]
    assert all(not item.billable and not item.charged for item in outcomes)
    assert [item.failure_code for item in outcomes] == ["invalid_json", "invalid_arguments"]
    assert marker not in repr([item.bounded_metadata() for item in outcomes])
    assert marker not in "".join(item.text for item in outcomes)


@pytest.mark.asyncio
async def test_inflight_and_completed_reuse_execute_once_in_original_order() -> None:
    invoked = 0
    release = asyncio.Event()

    async def invoke(tool, context, arguments):
        nonlocal invoked
        invoked += 1
        await release.wait()
        return ToolCallOutcome("safe-result", ToolCallStatus.SUCCEEDED, 0)

    call = {
        "name": "read",
        "arguments": {"options": {"limit": 2, "mode": "brief"}, "path": "a.txt"},
    }
    cache = ToolCallCache()
    running = asyncio.create_task(
        execute_tool_calls(
            [{"id": "first", **call}, {"id": "second", **call}],
            {"read": _tool()},
            object(),
            concurrency=2,
            invoker=invoke,
            cache=cache,
            dedup_safe=lambda name: name == "read",
            dedup_mode="enforce",
        )
    )
    await asyncio.sleep(0)
    release.set()
    first_round = await running

    assert invoked == 1
    assert first_round[0].reused is False
    assert first_round[1].reused is True
    assert first_round[1].dedup_reason == DedupReason.INFLIGHT.value
    assert first_round[1].charged is False

    second_round = await execute_tool_calls(
        [{"id": "third", **call}],
        {"read": _tool()},
        object(),
        concurrency=1,
        invoker=invoke,
        cache=cache,
        dedup_safe=lambda _name: True,
    )
    assert invoked == 1
    assert second_round[0].dedup_reason == DedupReason.COMPLETED.value


@pytest.mark.asyncio
async def test_retryable_failure_is_not_cached_but_terminal_outcome_is() -> None:
    invocations = 0

    async def retryable(tool, context, arguments):
        nonlocal invocations
        invocations += 1
        return ToolCallOutcome(
            "bounded unavailable",
            ToolCallStatus.FAILED,
            0,
            retryable=True,
            billable=False,
            failure_code=ToolFailureCode.UNAVAILABLE,
        )

    cache = ToolCallCache()
    call = {
        "id": "one",
        "name": "read",
        "arguments": {"path": "a", "options": {"mode": "brief"}},
    }
    for _ in range(2):
        await execute_tool_calls(
            [call],
            {"read": _tool()},
            None,
            concurrency=1,
            invoker=retryable,
            cache=cache,
            dedup_safe=lambda _name: True,
        )
    assert invocations == 2
    assert cache.completed == {}

    async def terminal(tool, context, arguments):
        nonlocal invocations
        invocations += 1
        return ToolCallOutcome("done", ToolCallStatus.TERMINAL, 0)

    terminal_cache = ToolCallCache()
    first = await execute_tool_calls(
        [call],
        {"read": _tool()},
        None,
        concurrency=1,
        invoker=terminal,
        cache=terminal_cache,
        dedup_safe=lambda _name: True,
    )
    second = await execute_tool_calls(
        [call],
        {"read": _tool()},
        None,
        concurrency=1,
        invoker=terminal,
        cache=terminal_cache,
        dedup_safe=lambda _name: True,
    )
    assert first[0].terminal
    assert second[0].reused and second[0].terminal
