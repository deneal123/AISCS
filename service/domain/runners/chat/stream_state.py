"""State transitions for the streamed model/tool loop.

The transport loop remains in :mod:`chat_stream_loop`; this module owns the mutable
run state and deterministic transitions around grounding, workspace control, tool
execution, prompt budget, and continuation.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from service.domain.client.protocol import ProviderRoundReceipt
from service.domain.execution.context import RunExecutionContext
from service.domain.execution.grounding import GroundingFailureCode, GroundingState
from service.domain.runners.chat.tool_state import (
    compact_workspace_context,
    exceeds_prompt_budget,
    prompt_budget_events,
    tool_round_cap_events,
)
from service.domain.runners.chat.workspace_control import control_gate, workspace_safe_boundary
from service.domain.runners.support import _CONTINUE_NUDGE
from service.domain.runners.tool_runtime import ToolCallCache
from service.domain.usage.ledger import UsageReceipt, UsageScope
from service.events import AgentEvent, EventType
from service.shared import deadline

LENGTH_NOTE = "\n\n_…ответ достиг лимита длины. Напишите «продолжи», чтобы я продолжил._"
_GROUNDING_REPAIR_NUDGE = (
    "Перед ответом вызови доступный инструмент, обязательный по правилам. "
    "Не выдумывай результат и не повторяй уже выполненный вызов инструмента."
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
    from service.domain.execution.context import require_execution

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


def _prepare_grounding_repair(state: ChatStreamLoopState) -> bool:
    from service.domain.runners.harness.continuation import claim_protocol_repair

    execution = state.execution
    if not claim_protocol_repair(execution):
        return False
    if state.segment:
        state.convo.append({"role": "assistant", "content": state.segment})
    state.convo.append({"role": "user", "content": _GROUNDING_REPAIR_NUDGE})
    state.segment = ""
    state.round_messages = state.convo
    state.tool_choice = execution.grounding.exact_tool_choice()
    return True


def pre_round_gate(state: ChatStreamLoopState, *, agent_name: str) -> tuple[list[AgentEvent], bool]:
    execution = state.execution
    if state.tool_summary.get("workspace_control") in {"blocked", "cancelled"}:
        return [], True
    if execution.task.active and execution.task.stop_reason == "no_progress":
        note = (
            "\n\nВыполнение остановлено: повторные действия не дают прогресса. Задача не завершена."
        )
        state.collected += note
        state.finalizing = True
        return [AgentEvent(type=EventType.STREAM_CHUNK, agent_name=agent_name, data=note)], True
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
    state.execution.task.stop_reason = "prompt_budget"
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
        if not _prepare_grounding_repair(state):
            return fail_grounding(state, agent_name=agent_name), LoopDecision.STOP
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
    async for boundary_event in control_gate(state, agent_name=agent_name):
        yield boundary_event
    if state.finalizing:
        yield LoopDecision.STOP
        return

    ide = isinstance((state.execution.resources.workspace_ref or {}).get("ide_context"), dict)
    if not state.execution.claim_task_round(limit=16 if ide else None):
        state.finalizing = True
        yield LoopDecision.STOP
        return
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
    if execution.question.prompt is not None:
        from service.domain.runners.human_question_pause import checkpoint_question_pause

        async for event in checkpoint_question_pause(state, tool_calls, agent_name=agent_name):
            yield event
        yield LoopDecision.STOP
        return
    grounding_state = execution.grounding.finish_tool_round()
    state.segment = ""
    if grounding_state is GroundingState.REPAIR:
        if event := grounding_event(agent_name):
            yield event
        if not _prepare_grounding_repair(state):
            for event in fail_grounding(state, agent_name=agent_name):
                yield event
            yield LoopDecision.STOP
            return
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

    async for boundary_event in control_gate(state, agent_name=agent_name):
        yield boundary_event
    if state.finalizing:
        yield LoopDecision.STOP
        return

    from service.domain.runners.harness.completion import verified_ide_report

    if event := await verified_ide_report(state, tool_calls, agent_name=agent_name):
        yield event
        yield LoopDecision.STOP
        return

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
    from service.domain.runners.ide.repair import prepare_verification_repair

    if prepare_verification_repair(state):
        from service.domain.runners.harness.continuation import advance_model_continuation

        await advance_model_continuation(state, agent_name=agent_name)
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
        execution.task.stop_reason = "round_limit"
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
    "workspace_safe_boundary",
]
