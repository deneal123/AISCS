"""Bounded terminal-tool repair inside the existing, metered provider session."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable

from service.domain.client.protocol import ProviderStreamEventKind
from service.domain.client.registry import max_provider_timeout_sec
from service.domain.runners.chat.provider_round import provider_events
from service.domain.runners.chat.stream_state import ChatStreamLoopState
from service.domain.runners.chat.tool_state import exceeds_prompt_budget
from service.domain.runners.chat.workspace_control import control_gate
from service.domain.runners.harness.continuation import (
    advance_model_continuation,
    claim_protocol_repair,
)
from service.events import AgentEvent, EventType
from service.shared import deadline
from service.shared.harness_protocol import HarnessFailure

_NAME = "ide_finish_task"
_INSTRUCTION = (
    "Заверши запрос вызовом ide_finish_task. Сожми свой последний ответ в 1–2 понятных "
    "пользователю предложения, до 280 символов: результат, причина невыполненного и "
    "следующий шаг или вопрос, если он есть. Не заменяй смысл технической статистикой. "
    "Не придумывай изменения. Пустой проект не мешает создать новый файл. "
    "Не повторяй файловые операции. Сейчас доступен только инструмент итога."
    " Укажи outcome=changed только при подтверждённых записях; иначе unchanged или blocked."
)


def _report_tools(state: ChatStreamLoopState) -> list:
    """Допуск отчёта: выбранный IDE, доступный инструмент и оставшиеся лимиты."""
    execution = state.execution
    if (
        execution.workspace.ide_summary
        or (execution.harness is not None and execution.harness.failure)
        or execution.cancelled
        or state.finalizing
        or state.tool_rounds >= state.max_tool_rounds
        or (
            execution.task_state is not None
            and execution.task_state.rounds >= execution.task_state.contract.round_limit
        )
        or not state.segment.strip()
        or deadline.must_finalize()
        or not isinstance((execution.resources.workspace_ref or {}).get("ide_context"), dict)
    ):
        return []
    tools = [
        tool for tool in state.openai_tools or [] if tool.get("function", {}).get("name") == _NAME
    ]
    return tools if _NAME in state.tool_index else []


async def finish_ide_response(
    state: ChatStreamLoopState,
    *,
    agent_name: str,
    stream: Callable,
    execute_tool_round: Callable,
    estimate_prompt_tokens: Callable,
    requested_calls: bool = False,
    finish_reason: str | None = None,
) -> AsyncGenerator[AgentEvent]:
    """Repair a skipped finish once; never enable or replay a workspace mutation."""
    if requested_calls or finish_reason == "length":
        return
    execution = state.execution
    tools = _report_tools(state)
    if not tools:
        return
    async for event in control_gate(state, agent_name=agent_name):
        yield event
    if state.finalizing:
        return
    messages = [
        *state.convo,
        {"role": "assistant", "content": state.segment},
        {"role": "user", "content": _INSTRUCTION},
    ]
    estimated = estimate_prompt_tokens(messages, tools)
    if exceeds_prompt_budget(
        budget=state.prompt_budget, spent=state.estimated_prompt_spent, next_prompt=estimated
    ):
        return
    if not claim_protocol_repair(execution, fail_grounding=False):
        return
    state.estimated_prompt_spent += estimated
    state.round_messages = messages
    # Это новая оплачиваемая попытка, а не новый запрос к уже занятому slot.
    # Checkpoint с расходом repair фиксируется до dispatch; неизвестный ACK не
    # разрешает генерацию или выполнение инструмента повторно.
    await advance_model_continuation(state, agent_name=agent_name)
    calls = []
    try:
        # Буферизованный CPU-транспорт может ещё законно генерировать ответ после
        # 15 секунд. Не обрываем его раньше провайдерного срока; общий срок задачи
        # по-прежнему ограничивает ожидание, а Stop проверяется отдельным gate.
        async with asyncio.timeout(deadline.clamp(max_provider_timeout_sec() + 5.0)):
            async for event in provider_events(
                stream,
                messages=messages,
                model=state.model,
                max_tokens=min(state.max_tokens, 512),
                tools=tools,
                pin_provider=state.pinned_provider,
                tool_choice={"type": "function", "function": {"name": _NAME}},
                provider_session=state.provider_session,
            ):
                if event.kind is ProviderStreamEventKind.TOOL_CALLS:
                    calls = list(event.tool_calls)
    except HarnessFailure:
        raise
    except Exception:  # noqa: BLE001 — preserve the completed reply; no provider-error payload
        return
    async for event in control_gate(state, agent_name=agent_name):
        yield event
    if state.finalizing:
        return
    # Ignore hallucinated operations and duplicate finish calls, even if the provider
    # disregards forced tool_choice. Text is never appended to the full Chat reply.
    call = next((call for call in calls if call.get("name") == _NAME), None)
    if call is None or execution.cancelled or deadline.must_finalize():
        return
    if not execution.claim_task_round(limit=16):
        return
    state.tool_rounds += 1
    async for event in execute_tool_round(
        messages,
        [call],
        {_NAME: state.tool_index[_NAME]},
        state.tool_ctx,
        "",
        state.billed,
        round_number=state.tool_rounds,
        summary=state.tool_summary,
        cache=state.tool_cache,
        dedup_mode=state.tool_dedup_mode,
    ):
        yield event
    from service.domain.runners.harness.completion import verified_ide_report

    if event := await verified_ide_report(state, [call], agent_name=agent_name):
        yield event


async def finalize_ide_output(state, *, agent_name) -> AsyncGenerator[AgentEvent]:
    """Публикация IDE-итога — не ответственность транспорта или свободного текста модели."""
    from service.domain.runners.harness.completion import verified_ide_completion
    from service.domain.runners.ide.repair import INCOMPLETE_MESSAGE, withhold_unverified_text

    if (
        state.collected.strip()
        or not withhold_unverified_text(state.execution)
        or state.execution.question.prompt is not None
    ):
        return
    if event := await verified_ide_completion(state, agent_name=agent_name):
        yield event
        return
    state.collected = INCOMPLETE_MESSAGE
    yield AgentEvent(
        type=EventType.STREAM_CHUNK,
        agent_name=agent_name,
        data=INCOMPLETE_MESSAGE,
        metadata={"model": state.model},
    )
