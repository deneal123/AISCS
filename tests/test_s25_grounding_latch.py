"""S25 deterministic grounding and ledger-native stream contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.domain.grounding import GroundingFailureCode, GroundingState
from service.domain.run_context import (
    GroundingRequirement,
    PrivateRunResources,
    use_run_execution,
)
from service.domain.runners.chat_stream_loop import ChatStreamLoopState, run_streamed_tool_loop
from service.domain.runners.tool_runtime import (
    ToolCallOutcome,
    ToolCallStatus,
    ToolFailureCode,
)
from service.domain.tools.function_tools import analyze_data
from service.events import EventType


def _tool(name: str = "ws_read") -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "Synthetic tool.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    }


class _Disclosure:
    def __init__(self, tools: list[dict]) -> None:
        self.tools = tools
        self.recorded = []

    def record(self, event) -> None:
        self.recorded.append(event)

    async def select(self, **_kwargs):
        return SimpleNamespace(
            toolset=SimpleNamespace(tools=self.tools),
            estimated_prompt_tokens=0,
            events=[],
        )


def _state(execution, disclosure: _Disclosure) -> ChatStreamLoopState:
    messages = [{"role": "user", "content": "synthetic"}]
    return ChatStreamLoopState(
        execution=execution,
        usage_scope=execution.usage.open_scope(),
        messages=messages,
        convo=list(messages),
        round_messages=list(messages),
        openai_tools=disclosure.tools,
        tool_index={"ws_read": analyze_data},
        tool_ctx={},
        disclosure_controller=disclosure,
        tool_summary={},
        model="synthetic-model",
        max_tokens=100,
        max_continuations=0,
        max_tool_rounds=3,
        prompt_budget=10_000,
        estimated_prompt_spent=0,
        context=None,
        tool_choice={"type": "function", "function": {"name": "ws_read"}},
    )


def _configure(execution) -> None:
    execution.policy.grounding_reason = GroundingRequirement.WORKSPACE_EXPLICIT
    execution.grounding.configure(
        requirement=execution.policy.grounding_reason,
        preferred_tool="ws_read",
        offered_names=["ws_read"],
        candidate_count=1,
    )


def _stream_script(rounds: list[dict], seen_choices: list[object]):
    calls = {"index": 0}

    async def stream(*, round_state=None, tool_choice=None, model=None, **_kwargs):
        seen_choices.append(tool_choice)
        item = rounds[calls["index"]]
        calls["index"] += 1
        if round_state is not None:
            round_state.update(
                {
                    "prompt": 5,
                    "completion": 2,
                    "total": 7,
                    "model": model,
                    "finish_reason": item.get("finish_reason", "stop"),
                    **({"tool_calls": item["tool_calls"]} if item.get("tool_calls") else {}),
                }
            )
        if text := item.get("text"):
            yield text

    return stream


def _executor(execution, outcomes: list[ToolCallOutcome], executed: list[str]):
    async def execute(convo, calls, *_args, **_kwargs):
        convo.append({"role": "assistant", "content": None, "tool_calls": calls})
        for call in calls:
            outcome = outcomes.pop(0)
            executed.append(str(call.get("name")))
            execution.grounding.observe_outcome(str(call.get("name") or ""), outcome)
            convo.append(
                {
                    "role": "tool",
                    "tool_call_id": str(call.get("id") or "call"),
                    "content": outcome.text,
                }
            )
        if False:
            yield None

    return execute


@pytest.mark.asyncio
async def test_missing_call_is_repaired_once_and_pre_grounding_text_is_withheld() -> None:
    rounds = [
        {"text": "PRIVATE_UNGROUNDED"},
        {
            "tool_calls": [
                {"id": "c1", "name": "ws_read", "arguments": "{}"},
            ],
            "finish_reason": "tool_calls",
        },
        {"text": "grounded final"},
    ]
    choices: list[object] = []
    executed: list[str] = []
    disclosure = _Disclosure([_tool()])

    with use_run_execution(PrivateRunResources()) as execution:
        _configure(execution)
        state = _state(execution, disclosure)
        events = [
            event
            async for event in run_streamed_tool_loop(
                state,
                agent_name="general",
                execute_tool_round=_executor(
                    execution,
                    [ToolCallOutcome("ok", ToolCallStatus.SUCCEEDED, 0.0)],
                    executed,
                ),
                estimate_prompt_tokens=lambda *_args: 1,
                stream=_stream_script(rounds, choices),
            )
        ]

        chunks = [str(event.data) for event in events if event.type == EventType.STREAM_CHUNK]
        assert chunks == ["grounded final"]
        assert "PRIVATE_UNGROUNDED" not in str(events)
        assert execution.grounding.state is GroundingState.SATISFIED
        assert execution.grounding.repair_count == 1
        assert len(execution.usage.receipts) == 3

    assert executed == ["ws_read"]
    assert choices[0] == choices[1]
    assert choices[2] is None


@pytest.mark.asyncio
async def test_invalid_arguments_get_one_repair_then_safe_failure() -> None:
    calls = [{"id": "c1", "name": "ws_read", "arguments": "{"}]
    rounds = [
        {"tool_calls": calls, "finish_reason": "tool_calls"},
        {"tool_calls": calls, "finish_reason": "tool_calls"},
    ]
    invalid = ToolCallOutcome(
        "safe invalid",
        ToolCallStatus.INVALID,
        0.0,
        billable=False,
        failure_code=ToolFailureCode.INVALID_JSON,
    )
    choices: list[object] = []
    executed: list[str] = []
    disclosure = _Disclosure([_tool()])

    with use_run_execution(PrivateRunResources()) as execution:
        _configure(execution)
        state = _state(execution, disclosure)
        events = [
            event
            async for event in run_streamed_tool_loop(
                state,
                agent_name="general",
                execute_tool_round=_executor(execution, [invalid, invalid], executed),
                estimate_prompt_tokens=lambda *_args: 1,
                stream=_stream_script(rounds, choices),
            )
        ]

        assert execution.grounding.state is GroundingState.FAILED
        assert execution.grounding.failure_code is GroundingFailureCode.INVALID_ARGUMENTS
        assert execution.grounding.repair_count == 1
        assert all(
            "ws_read" not in str((event.metadata or {}).get("tool_intent")) for event in events
        )
        chunks = [event.data for event in events if event.type == EventType.STREAM_CHUNK]
        assert len(chunks) == 1
        assert "обязательные данные" in chunks[0]

    assert executed == ["ws_read", "ws_read"]
    assert len(choices) == 2


@pytest.mark.asyncio
async def test_actual_tool_failure_is_not_retried() -> None:
    rounds = [
        {
            "tool_calls": [{"id": "c1", "name": "ws_read", "arguments": "{}"}],
            "finish_reason": "tool_calls",
        }
    ]
    failed = ToolCallOutcome(
        "safe failure",
        ToolCallStatus.FAILED,
        0.0,
        retryable=True,
        billable=False,
        failure_code=ToolFailureCode.TRANSPORT,
    )
    choices: list[object] = []
    executed: list[str] = []
    disclosure = _Disclosure([_tool()])

    with use_run_execution(PrivateRunResources()) as execution:
        _configure(execution)
        state = _state(execution, disclosure)
        events = [
            event
            async for event in run_streamed_tool_loop(
                state,
                agent_name="general",
                execute_tool_round=_executor(execution, [failed], executed),
                estimate_prompt_tokens=lambda *_args: 1,
                stream=_stream_script(rounds, choices),
            )
        ]

        assert execution.grounding.state is GroundingState.FAILED
        assert execution.grounding.repair_count == 0
        assert len(execution.usage.receipts) == 1
        assert any(event.type == EventType.STREAM_CHUNK for event in events)

    assert executed == ["ws_read"]
    assert len(choices) == 1


@pytest.mark.asyncio
async def test_provider_failure_before_grounding_returns_only_safe_terminal_text() -> None:
    marker = "PRIVATE_PROVIDER_FAILURE_BODY"
    disclosure = _Disclosure([_tool()])

    async def stream(**_kwargs):
        if False:
            yield ""
        raise RuntimeError(marker)

    with use_run_execution(PrivateRunResources()) as execution:
        _configure(execution)
        state = _state(execution, disclosure)
        events = [
            event
            async for event in run_streamed_tool_loop(
                state,
                agent_name="general",
                execute_tool_round=_executor(execution, [], []),
                estimate_prompt_tokens=lambda *_args: 1,
                stream=stream,
            )
        ]

        assert execution.grounding.state is GroundingState.FAILED
        assert execution.grounding.failure_code is GroundingFailureCode.PROVIDER_FAILURE
        assert execution.grounding.repair_count == 0

    assert marker not in str(events)
    chunks = [event.data for event in events if event.type == EventType.STREAM_CHUNK]
    assert len(chunks) == 1
    assert "обязательные данные" in chunks[0]
