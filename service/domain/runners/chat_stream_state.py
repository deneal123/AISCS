"""State transitions for the streamed model/tool loop.

The transport loop remains in :mod:`chat_stream_loop`; this module owns the mutable
run state and deterministic transitions around grounding, workspace control, tool
execution, prompt budget, and continuation.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from service.domain.client.protocol import ProviderRoundReceipt
from service.domain.grounding import GroundingFailureCode, GroundingState
from service.domain.run_context import RunExecutionContext
from service.domain.runners.chat_tool_state import (
    compact_workspace_context,
    exceeds_prompt_budget,
    prompt_budget_events,
    tool_round_cap_events,
)
from service.domain.runners.support import _CONTINUE_NUDGE
from service.domain.runners.tool_execution import ToolCallCache
from service.domain.tools.workspace_client import WorkspaceUnavailable
from service.domain.tools.workspace_client import call as workspace_call
from service.domain.usage_ledger import UsageReceipt, UsageScope
from service.events import AgentEvent, EventType
from service.shared import deadline

LENGTH_NOTE = "\n\n_…ответ достиг лимита длины. Напишите «продолжи», чтобы я продолжил._"
_GROUNDING_REPAIR_NUDGE = (
    "Use an offered tool required by policy before answering. "
    "Do not infer the result and do not repeat a tool that already ran."
)
_GROUNDING_FAILURE_MESSAGE = (
    "Не удалось надёжно получить обязательные данные из инструмента. "
    "Повторите запрос позже или уточните действие."
)


@dataclass(slots=True)
class ChatRoundState:
    """Typed result of one accepted provider round."""

    text: str = ""
    reasoning: str = ""
    reasoning_tokens: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None
    receipt: UsageReceipt | None = None
    provider_round: ProviderRoundReceipt | None = None


@dataclass
class ChatStreamLoopState:
    execution: RunExecutionContext
    usage_scope: UsageScope
    messages: list[dict]
    convo: list[dict]
    round_messages: list[dict]
    openai_tools: list | None
    tool_index: dict[str, Any]
    tool_ctx: Any
    disclosure_controller: Any
    tool_summary: dict[str, Any]
    model: str
    max_tokens: int
    max_continuations: int
    max_tool_rounds: int
    prompt_budget: int
    estimated_prompt_spent: int
    context: Any | None
    collected: str = ""
    segment: str = ""
    continuations: int = 0
    tool_rounds: int = 0
    finalizing: bool = False
    tool_cap_hit: bool = False
    repo_context_compacted: bool = False
    pinned_provider: str | None = None
    billed: set[str] | None = None
    tool_cache: ToolCallCache | None = None
    tool_dedup_mode: str = "observe"
    tool_choice: str | dict | None = None

    def __post_init__(self) -> None:
        if self.billed is None:
            self.billed = set()
        if self.tool_cache is None:
            self.tool_cache = ToolCallCache()

    @property
    def provider_session(self):
        return self.execution.provider_session


class LoopDecision(StrEnum):
    NEXT = "next"
    STOP = "stop"


def grounding_event(agent_name: str) -> AgentEvent | None:
    from service.domain.run_context import require_execution

    execution = require_execution()
    if not execution.grounding.required:
        return None
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name=agent_name,
        data=None,
        metadata={
            "kind": "tool_intent",
            "tool_intent": execution.grounding.bounded_metadata(),
        },
    )


def fail_grounding(
    state: ChatStreamLoopState,
    *,
    agent_name: str,
    code: GroundingFailureCode | None = None,
) -> list[AgentEvent]:
    execution = state.execution
    if code is not None:
        execution.grounding.fail(code)
    state.segment = ""
    state.finalizing = True
    state.collected = _GROUNDING_FAILURE_MESSAGE
    events: list[AgentEvent] = []
    if intent := grounding_event(agent_name):
        events.append(intent)
    events.append(
        AgentEvent(
            type=EventType.STREAM_CHUNK,
            agent_name=agent_name,
            data=_GROUNDING_FAILURE_MESSAGE,
            metadata={"model": state.model},
        )
    )
    return events


def _prepare_grounding_repair(state: ChatStreamLoopState) -> None:
    execution = state.execution
    if state.segment:
        state.convo.append({"role": "assistant", "content": state.segment})
    state.convo.append({"role": "user", "content": _GROUNDING_REPAIR_NUDGE})
    state.segment = ""
    state.round_messages = state.convo
    state.tool_choice = execution.grounding.exact_tool_choice()


def _workspace_ref(context: Any | None) -> dict[str, Any] | None:
    value = (
        context.get("workspace_ref")
        if isinstance(context, dict)
        else getattr(context, "workspace_ref", None)
    )
    return value if isinstance(value, dict) and value.get("coordination_capability") else None


async def workspace_safe_boundary(
    state: ChatStreamLoopState, *, agent_name: str
) -> AsyncGenerator[AgentEvent | bool]:
    """Stop between rounds on the backend-owned pause/cancel control plane."""

    reference = _workspace_ref(state.context)
    if reference is None:
        yield False
        return
    announced_pause = False
    while True:
        if deadline.must_finalize():
            yield True
            return
        try:
            response = await workspace_call(reference, "collaboration/boundary", {})
        except WorkspaceUnavailable:
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=agent_name,
                data=None,
                metadata={"kind": "workspace_collaboration", "state": "unavailable"},
            )
            yield False
            return
        boundary_state = str(response.get("state") or "running")
        if boundary_state == "running":
            if announced_pause:
                yield AgentEvent(
                    type=EventType.STATUS_UPDATE,
                    agent_name=agent_name,
                    data=None,
                    metadata={"kind": "workspace_collaboration", "state": "resumed"},
                )
            yield False
            return
        if boundary_state == "cancelled":
            state.execution.cancel()
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=agent_name,
                data=None,
                metadata={"kind": "workspace_collaboration", "state": "cancelled"},
            )
            yield True
            return
        if not announced_pause:
            announced_pause = True
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=agent_name,
                data=None,
                metadata={"kind": "workspace_collaboration", "state": "paused"},
            )
        await asyncio.sleep(0.5)


def pre_round_gate(state: ChatStreamLoopState, *, agent_name: str) -> tuple[list[AgentEvent], bool]:
    execution = state.execution
    if execution.cancelled:
        events = (
            fail_grounding(
                state,
                agent_name=agent_name,
                code=GroundingFailureCode.CANCELLED,
            )
            if execution.grounding.blocks_output
            else []
        )
        state.finalizing = True
        return events, True
    if execution.grounding.state is GroundingState.FAILED:
        return fail_grounding(state, agent_name=agent_name), True
    if execution.grounding.blocks_output:
        if deadline.must_finalize():
            return (
                fail_grounding(
                    state,
                    agent_name=agent_name,
                    code=GroundingFailureCode.DEADLINE,
                ),
                True,
            )
        execution.grounding.begin_round()
    return [], False


def prompt_budget_gate(
    state: ChatStreamLoopState,
    *,
    agent_name: str,
    estimate_prompt_tokens: Callable[[list[dict], list | None], int],
) -> tuple[list[AgentEvent], bool]:
    estimated = estimate_prompt_tokens(state.round_messages, state.openai_tools)
    if not exceeds_prompt_budget(
        budget=state.prompt_budget,
        spent=state.estimated_prompt_spent,
        next_prompt=estimated,
    ):
        state.estimated_prompt_spent += estimated
        return [], False
    execution = state.execution
    if execution.grounding.blocks_output:
        return (
            fail_grounding(
                state,
                agent_name=agent_name,
                code=GroundingFailureCode.PROMPT_BUDGET,
            ),
            True,
        )
    events, safety_note = prompt_budget_events(
        state.tool_summary,
        budget=state.prompt_budget,
        estimated=state.estimated_prompt_spent + estimated,
        round_number=state.tool_rounds + 1,
        agent_name=agent_name,
        model=state.model,
    )
    state.collected += safety_note
    return events, True


def model_grounding_transition(
    state: ChatStreamLoopState,
    tool_calls: list[dict],
    *,
    agent_name: str,
) -> tuple[list[AgentEvent], LoopDecision | None]:
    execution = state.execution
    grounding_state = execution.grounding.finish_model_round(tool_calls)
    if grounding_state is GroundingState.REPAIR and not tool_calls:
        events = [event] if (event := grounding_event(agent_name)) else []
        _prepare_grounding_repair(state)
        return events, LoopDecision.NEXT
    if grounding_state is GroundingState.FAILED:
        return fail_grounding(state, agent_name=agent_name), LoopDecision.STOP
    if not execution.grounding.blocks_output:
        state.tool_choice = None
    return [], None


async def run_requested_tools(
    state: ChatStreamLoopState,
    tool_calls: list[dict],
    *,
    agent_name: str,
    execute_tool_round: Callable[..., AsyncGenerator[AgentEvent]],
) -> AsyncGenerator[AgentEvent | LoopDecision]:
    async for boundary_event in workspace_safe_boundary(state, agent_name=agent_name):
        if isinstance(boundary_event, bool):
            if boundary_event:
                state.finalizing = True
                state.tool_summary["workspace_control"] = "cancelled"
                yield LoopDecision.STOP
                return
        else:
            yield boundary_event

    state.tool_rounds += 1
    async for event in execute_tool_round(
        state.convo,
        tool_calls,
        state.tool_index,
        state.tool_ctx,
        state.segment,
        state.billed or set(),
        round_number=state.tool_rounds,
        summary=state.tool_summary,
        cache=state.tool_cache,
        dedup_mode=state.tool_dedup_mode,
    ):
        state.disclosure_controller.record(event)
        yield event

    execution = state.execution
    grounding_state = execution.grounding.finish_tool_round()
    state.segment = ""
    if grounding_state is GroundingState.REPAIR:
        if event := grounding_event(agent_name):
            yield event
        _prepare_grounding_repair(state)
        yield LoopDecision.NEXT
        return
    if grounding_state is GroundingState.FAILED:
        for event in fail_grounding(state, agent_name=agent_name):
            yield event
        yield LoopDecision.STOP
        return
    if grounding_state is GroundingState.SATISFIED:
        state.tool_choice = None
        if event := grounding_event(agent_name):
            yield event
    if not state.repo_context_compacted and compact_workspace_context(
        state.convo, tool_calls, state.context
    ):
        state.repo_context_compacted = True
        state.tool_summary["repo_context_compacted"] = True

    async for boundary_event in workspace_safe_boundary(state, agent_name=agent_name):
        if isinstance(boundary_event, bool):
            if boundary_event:
                state.finalizing = True
                state.tool_summary["workspace_control"] = "cancelled"
                yield LoopDecision.STOP
                return
        else:
            yield boundary_event

    disclosure = await state.disclosure_controller.select(
        stage=state.tool_rounds + 1,
        remaining_prompt_tokens=(state.prompt_budget - state.estimated_prompt_spent)
        if state.prompt_budget
        else None,
    )
    state.openai_tools = disclosure.toolset.tools
    state.estimated_prompt_spent += disclosure.estimated_prompt_tokens
    for event in disclosure.events:
        yield event
    state.round_messages = state.convo
    yield LoopDecision.NEXT


def tail_transition(
    state: ChatStreamLoopState,
    tool_calls: list[dict],
    round_state: ChatRoundState,
    *,
    agent_name: str,
) -> tuple[list[AgentEvent], LoopDecision]:
    execution = state.execution
    if (
        tool_calls
        and execution.grounding.blocks_output
        and state.tool_rounds >= state.max_tool_rounds
    ):
        return (
            fail_grounding(
                state,
                agent_name=agent_name,
                code=GroundingFailureCode.TOOL_FAILURE,
            ),
            LoopDecision.STOP,
        )
    events = list(
        tool_round_cap_events(
            tool_calls,
            summary=state.tool_summary,
            agent_name=agent_name,
            round_number=state.tool_rounds,
        )
    )
    if events:
        state.tool_cap_hit = True
    if (
        round_state.finish_reason == "length"
        and state.continuations < state.max_continuations
        and bool(state.segment.strip())
    ):
        state.continuations += 1
        state.round_messages = state.convo + [
            {"role": "assistant", "content": state.segment},
            {"role": "user", "content": _CONTINUE_NUDGE},
        ]
        return events, LoopDecision.NEXT
    if round_state.finish_reason == "length" and state.collected.strip():
        state.collected += LENGTH_NOTE
        events.append(
            AgentEvent(
                type=EventType.STREAM_CHUNK,
                agent_name=agent_name,
                data=LENGTH_NOTE,
                metadata={"model": state.model},
            )
        )
    return events, LoopDecision.STOP


__all__ = [
    "ChatStreamLoopState",
    "ChatRoundState",
    "LENGTH_NOTE",
    "LoopDecision",
    "fail_grounding",
    "model_grounding_transition",
    "pre_round_gate",
    "prompt_budget_gate",
    "run_requested_tools",
    "tail_transition",
]
