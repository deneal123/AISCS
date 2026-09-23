"""Deterministic golden contract for the streamed tool loop.

These scenarios deliberately use only scripted model responses and mock tools.  They are
part of the normal agents pytest suite, so a regression blocks merge without sending a
prompt, tool argument, or user data outside the test process.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from service.domain import base as base_mod
from service.domain.runners import chat_run, tool_loop
from service.domain.runners.tool_execution import ToolCallCache, ToolCallOutcome
from service.domain.subagents.general import GeneralAgent
from service.events import EventType
from service.schemas.agents import UserContext


@dataclass(frozen=True, slots=True)
class GoldenScenario:
    name: str
    rounds: tuple[tuple[dict, ...], ...]
    expected_invocations: int
    expected_statuses: tuple[str, ...]
    expected_dedup_reason: str = ""


_SAME_ARGUMENTS_A = '{"q":"same","token":"golden-secret"}'
_SAME_ARGUMENTS_B = '{"token":"golden-secret","q":"same"}'

GOLDEN_SCENARIOS = (
    GoldenScenario(
        name="safe_inflight_duplicate",
        rounds=(
            (
                {"id": "one", "name": "search_web", "arguments": _SAME_ARGUMENTS_A},
                {"id": "two", "name": "search_web", "arguments": _SAME_ARGUMENTS_B},
            ),
        ),
        expected_invocations=1,
        expected_statuses=("succeeded", "reused"),
        expected_dedup_reason="inflight",
    ),
    GoldenScenario(
        name="safe_completed_duplicate",
        rounds=(
            ({"id": "one", "name": "search_web", "arguments": _SAME_ARGUMENTS_A},),
            ({"id": "two", "name": "search_web", "arguments": _SAME_ARGUMENTS_B},),
        ),
        expected_invocations=1,
        expected_statuses=("succeeded", "reused"),
        expected_dedup_reason="completed",
    ),
    GoldenScenario(
        name="distinct_arguments",
        rounds=(
            (
                {"id": "one", "name": "search_web", "arguments": '{"q":"first"}'},
                {"id": "two", "name": "search_web", "arguments": '{"q":"second"}'},
            ),
        ),
        expected_invocations=2,
        expected_statuses=("succeeded", "succeeded"),
    ),
    GoldenScenario(
        name="unsafe_workspace_write",
        rounds=(
            (
                {"id": "one", "name": "ws_write", "arguments": _SAME_ARGUMENTS_A},
                {"id": "two", "name": "ws_write", "arguments": _SAME_ARGUMENTS_B},
            ),
        ),
        expected_invocations=2,
        expected_statuses=("succeeded", "succeeded"),
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", GOLDEN_SCENARIOS, ids=lambda item: item.name)
async def test_tool_loop_golden_execution_contract(monkeypatch, scenario: GoldenScenario) -> None:
    """Exact calls, lifecycle ordering, billing and safe trace metadata are stable."""
    invocations: list[str] = []
    charged: list[str] = []

    async def invoke(_tool, _ctx, arguments):
        invocations.append(arguments)
        return "golden-result"

    monkeypatch.setattr(tool_loop, "_invoke_tool", invoke)
    monkeypatch.setattr(
        GeneralAgent,
        "_billable_tools_meta",
        classmethod(lambda _cls, name, _billed: charged.append(name) or {"tool_name": name}),
    )

    agent = GeneralAgent({"model": "golden-model"})
    cache = ToolCallCache()
    convo: list[dict] = []
    events = []
    expected_ids: list[str] = []
    for round_number, calls in enumerate(scenario.rounds, start=1):
        expected_ids.extend(str(call["id"]) for call in calls)
        events.extend(
            [
                event
                async for event in agent._execute_tool_round(
                    convo,
                    list(calls),
                    {str(call["name"]): "tool" for call in calls},
                    None,
                    "",
                    set(),
                    round_number=round_number,
                    cache=cache,
                    dedup_mode="enforce",
                )
            ]
        )

    terminal = [
        event.metadata["tool_progress"]
        for event in events
        if event.type == EventType.STATUS_UPDATE
        and event.metadata.get("kind") == "tool_progress"
        and event.metadata.get("tool_progress", {}).get("status") != "running"
    ]
    assert [item["status"] for item in terminal] == list(scenario.expected_statuses)
    assert len(invocations) == scenario.expected_invocations
    assert len(charged) == scenario.expected_invocations
    assert [
        message["tool_call_id"] for message in convo if message.get("role") == "tool"
    ] == expected_ids
    assert all("golden-secret" not in str(event.metadata) for event in events)
    if scenario.expected_dedup_reason:
        assert terminal[-1]["dedup_reason"] == scenario.expected_dedup_reason
    else:
        assert not any(item["dedup_reason"] for item in terminal)


@pytest.mark.asyncio
async def test_tool_loop_golden_retryability_contract(monkeypatch) -> None:
    """A model-directed retry is allowed only after a transient failure."""
    invocations = 0

    async def invoke(_tool, _ctx, _arguments):
        nonlocal invocations
        invocations += 1
        if invocations == 1:
            return ToolCallOutcome("temporary", "failed", 0.0, retryable=True, billable=False)
        return "recovered"

    monkeypatch.setattr(tool_loop, "_invoke_tool", invoke)
    agent = GeneralAgent({"model": "golden-model"})
    cache = ToolCallCache()
    terminal_statuses = []
    for call_id in ("first", "second"):
        events = [
            event
            async for event in agent._execute_tool_round(
                [],
                [{"id": call_id, "name": "search_web", "arguments": "{}"}],
                {"search_web": "tool"},
                None,
                "",
                set(),
                cache=cache,
                dedup_mode="enforce",
            )
        ]
        terminal_statuses.extend(
            event.metadata["tool_progress"]["status"]
            for event in events
            if event.type == EventType.STATUS_UPDATE
            and event.metadata.get("kind") == "tool_progress"
            and event.metadata.get("tool_progress", {}).get("status") != "running"
        )

    assert invocations == 2
    assert terminal_statuses == ["failed", "succeeded"]


@pytest.mark.asyncio
async def test_tool_loop_golden_provider_usage_and_terminal_contract(monkeypatch) -> None:
    """Tool rounds preserve provider pinning and sum provider usage into one terminal event."""
    pins: list[str | None] = []

    async def stream(*, model, round_state=None, pin_provider=None, **_kwargs):
        pins.append(pin_provider)
        if len(pins) == 1:
            if round_state is not None:
                round_state.update(
                    {
                        "provider": "golden-provider",
                        "prompt": 11,
                        "completion": 2,
                        "total": 13,
                        "model": model,
                        "tool_calls": [{"id": "tool-1", "name": "fetch_url", "arguments": "{}"}],
                    }
                )
            return
        yield "golden final"
        if round_state is not None:
            round_state.update({"prompt": 7, "completion": 3, "total": 10, "model": model})

    async def resolve_tools(_self, _model, _context=None):
        from service.domain.capabilities.tool_spec import ToolSet
        from service.domain.runners.support import _tools_to_openai
        from service.domain.tools.function_tools import DEFAULT_FUNCTION_TOOLS

        return ToolSet(tools=_tools_to_openai(DEFAULT_FUNCTION_TOOLS))

    async def invoke(_tool, _ctx, _arguments):
        return "fetched"

    monkeypatch.setattr(chat_run, "stream_chat_completion", stream)
    monkeypatch.setattr(tool_loop, "_invoke_tool", invoke)
    monkeypatch.setattr(
        base_mod.SimpleStreamingAgent, "_resolve_toolset", resolve_tools, raising=False
    )

    context = UserContext(user_id="", request_time=datetime.now(UTC))
    events = [
        event
        async for event in GeneralAgent({"model": "golden-model"})._run_chat_streamed(
            "golden", context
        )
    ]

    complete = [event for event in events if event.type == EventType.AGENT_COMPLETE]
    assert pins == [None, "golden-provider"]
    assert complete and complete[-1].metadata["token_usage"] == {
        "prompt": 18,
        "completion": 5,
        "total": 23,
        "model": "golden-model",
        "provider": "golden-provider",
    }
    assert "golden final" == "".join(
        event.data for event in events if event.type == EventType.STREAM_CHUNK
    )
