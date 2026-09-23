"""The mutable streamed tool-loop state, separate from chat-run setup/termination."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable

from service.domain.client import stream_provider_completion as stream_chat_completion
from service.domain.client.protocol import ProviderStreamEventKind, classify_provider_failure
from service.domain.grounding import GroundingFailureCode
from service.domain.runners.chat_provider_round import provider_events
from service.domain.runners.chat_stream_state import (
    ChatRoundState,
    ChatStreamLoopState,
    LoopDecision,
    fail_grounding,
    model_grounding_transition,
    pre_round_gate,
    prompt_budget_gate,
    run_requested_tools,
    tail_transition,
)
from service.domain.runners.chat_tool_state import (
    deadline_finalization,
    should_finalize,
)
from service.events import AgentEvent, EventType
from service.shared import deadline

_LENGTH_NOTE = "\n\n_…ответ достиг лимита длины. Напишите «продолжи», чтобы я продолжил._"


_GROUNDING_REPAIR_NUDGE = (
    "Use an offered tool required by policy before answering. "
    "Do not infer the result and do not repeat a tool that already ran."
)
_GROUNDING_FAILURE_MESSAGE = (
    "Не удалось надёжно получить обязательные данные из инструмента. "
    "Повторите запрос позже или уточните действие."
)


def _reasoning_event(round_state: ChatRoundState, agent_name: str, model: str) -> AgentEvent | None:
    if not round_state.reasoning:
        return None
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name=agent_name,
        data=round_state.reasoning,
        metadata={
            "kind": "reasoning",
            "model": model,
            "reasoning_tokens": round_state.reasoning_tokens,
        },
    )


async def _stream_provider_round(
    state: ChatStreamLoopState,
    round_state: ChatRoundState,
    *,
    agent_name: str,
    stream: Callable[..., AsyncGenerator[str]],
) -> AsyncGenerator[AgentEvent]:
    async for provider_event in provider_events(
        stream,
        messages=state.round_messages,
        model=state.model,
        max_tokens=state.max_tokens,
        tools=state.openai_tools,
        pin_provider=state.pinned_provider,
        tool_choice=state.tool_choice,
        provider_session=state.provider_session,
    ):
        if provider_event.kind is ProviderStreamEventKind.REASONING:
            round_state.reasoning = provider_event.text
            round_state.reasoning_tokens = int(provider_event.metadata.get("tokens", 0) or 0)
            continue
        if provider_event.kind is ProviderStreamEventKind.TOOL_CALLS:
            round_state.tool_calls = [dict(call) for call in provider_event.tool_calls]
            continue
        if provider_event.kind is ProviderStreamEventKind.COMPLETED:
            if provider_event.finish_reason:
                round_state.finish_reason = provider_event.finish_reason
            if provider_event.round_receipt is not None:
                round_state.provider_round = provider_event.round_receipt
                state.pinned_provider = provider_event.round_receipt.provider
            if provider_event.usage is not None:
                round_state.receipt = provider_event.usage
            continue
        delta = provider_event.text
        state.segment += delta
        round_state.text += delta
        if not state.execution.grounding.blocks_output:
            state.collected += delta
            yield AgentEvent(
                type=EventType.STREAM_CHUNK,
                agent_name=agent_name,
                data=delta,
                metadata={"model": state.model},
            )
    if not state.execution.grounding.blocks_output:
        if event := _reasoning_event(round_state, agent_name, state.model):
            yield event
    state.pinned_provider = state.pinned_provider or state.provider_session.pinned_provider


async def run_streamed_tool_loop(
    state: ChatStreamLoopState,
    *,
    agent_name: str,
    execute_tool_round: Callable[..., AsyncGenerator[AgentEvent]],
    estimate_prompt_tokens: Callable[[list[dict], list | None], int],
    stream: Callable[..., AsyncGenerator[str]] = stream_chat_completion,
) -> AsyncGenerator[AgentEvent]:
    """Run model/tool rounds, updating ``state`` for the caller's terminal path."""
    while True:
        gate_events, must_stop = pre_round_gate(state, agent_name=agent_name)
        for event in gate_events:
            yield event
        if must_stop:
            break
        budget_events, must_stop = prompt_budget_gate(
            state,
            agent_name=agent_name,
            estimate_prompt_tokens=estimate_prompt_tokens,
        )
        for event in budget_events:
            yield event
        if must_stop:
            break

        round_state = ChatRoundState()
        try:
            async for event in _stream_provider_round(
                state,
                round_state,
                agent_name=agent_name,
                stream=stream,
            ):
                yield event
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not state.execution.grounding.blocks_output:
                raise
            failure = classify_provider_failure(exc, provider=state.pinned_provider)
            code = (
                GroundingFailureCode.DEADLINE
                if failure.code.value == "timeout"
                else GroundingFailureCode.PROVIDER_FAILURE
            )
            for event in fail_grounding(state, agent_name=agent_name, code=code):
                yield event
            break
        tool_calls = round_state.tool_calls
        transition_events, decision = model_grounding_transition(
            state,
            tool_calls,
            agent_name=agent_name,
        )
        for event in transition_events:
            yield event
        if decision is LoopDecision.NEXT:
            continue
        if decision is LoopDecision.STOP:
            break

        if should_finalize(
            tool_calls,
            finalizing=state.finalizing,
            deadline_reached=deadline.must_finalize(),
        ):
            state.finalizing = True
            event, state.round_messages = deadline_finalization(
                state.convo,
                agent_name=agent_name,
                round_number=state.tool_rounds + 1,
                summary=state.tool_summary,
            )
            yield event
            state.openai_tools = None
            continue
        if tool_calls and state.tool_rounds < state.max_tool_rounds:
            decision = None
            async for item in run_requested_tools(
                state,
                tool_calls,
                agent_name=agent_name,
                execute_tool_round=execute_tool_round,
            ):
                if isinstance(item, LoopDecision):
                    decision = item
                else:
                    yield item
            if decision is LoopDecision.STOP:
                break
            continue

        tail_events, decision = tail_transition(
            state,
            tool_calls,
            round_state,
            agent_name=agent_name,
        )
        for event in tail_events:
            yield event
        if decision is LoopDecision.NEXT:
            continue
        break
