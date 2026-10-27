"""Путь исполнения через прямой chat/completions-стрим (без Agents SDK).

Раунды инструментов живут в соседнем `tool_loop`: там другая тема и другой повод для
правок.

⚠️ Существует потому, что у MWS, OpenRouter, GigaChat и RouterAI SDK-Responses-стрим
ненадёжен — часто не отдаёт дельты целиком. Здесь стрим идёт по токенам напрямую.

Это денежный путь: он ведёт цикл инструментов и отдаёт `token_usage`. От хозяина требует
`name`, `instructions`, `tools`, `model_settings` и методы `_build_messages`,
`_resolve_chat_model`, `_resolve_toolset`, `_build_tool_context` — состав держит
`tests/test_agent_runner_mixins.py`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from service.domain.client import stream_provider_completion as stream_chat_completion
from service.domain.client.protocol import classify_provider_failure
from service.domain.execution.context import RunExecutionContext, require_execution
from service.domain.runners.chat.preparation import prepare_chat_run
from service.domain.runners.chat.stream_loop import run_streamed_tool_loop
from service.domain.runners.chat.terminal import completed_event, tool_cap_message
from service.domain.runners.chat.tool_loop import (
    ToolRoundMixin,
    tool_summary_event,
)
from service.domain.runners.chat.tool_state import model_unavailable_event
from service.domain.usage.ledger import UsageScope
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext
from service.shared.token_budget import estimate_tokens

logger = logging.getLogger(__name__)


def _estimated_prompt_tokens(messages: list[dict], tools: list | None) -> int:
    """Консервативная оценка исходящего prompt с JSON схемами инструментов."""
    import json

    return estimate_tokens(json.dumps(messages, ensure_ascii=False, default=str)) + estimate_tokens(
        json.dumps(tools or [], ensure_ascii=False, default=str)
    )


def _chat_usage(execution: RunExecutionContext, scope: UsageScope) -> dict[str, Any]:
    """Read-only wire projection of receipts accepted during the chat stage."""

    usage = execution.usage.project_scope(scope)
    usage.pop("calls", None)
    if usage.get("provider") == "unknown":
        usage.pop("provider", None)
    return usage


class ChatRunMixin(ToolRoundMixin):
    """Прогон через прямой chat/completions-стрим. Требования — в докстринге модуля."""

    async def _finish_without_text(
        self,
        *,
        tool_cap_hit: bool,
        usage: dict[str, Any],
        model: str,
        tool_summary: dict[str, Any] | None = None,
    ) -> AsyncGenerator[AgentEvent]:
        """Завершить прогон, не давший текста, — ТАРИФИЦИРОВАВ уже сделанную работу.

        ⚠️ Обе ветки были бесплатными: при `tool_cap` сделано до `max_tool_rounds` полных
        вызовов с растущим контекстом, при пустом ответе оплачен как минимум промпт.
        прежний mutable usage заполнялся и выбрасывался, а резерв-флор не спасал — мета-вызовы дают
        `total_tokens > 0`, и флор не включается.
        """
        if tool_cap_hit:
            if tool_summary:
                yield tool_summary_event(tool_summary, self.name)
            yield AgentEvent(
                type=EventType.AGENT_COMPLETE,
                agent_name=self.name,
                data=f"Completed {self.name} (tool cap)",
                metadata={
                    "model": model,
                    "tool_cap_reached": True,
                    "token_usage": usage,
                    "tool_summary": tool_summary or {},
                },
            )
            return
        # ⚠️ ОТДЕЛЬНЫМ СОБЫТИЕМ, А НЕ В METADATA ОШИБКИ: мульти-интент намеренно
        # выбрасывает usage с ERROR-событий (`execution_plan._run_one_step` фильтрует
        # `event.type != ERROR`), и повесь мы его на ошибку — на том пути он терялся бы
        # снова, ровно так же незаметно.
        yield AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name=self.name,
            data="",
            metadata={"token_usage": usage, "kind": "empty_response_usage"},
        )
        if tool_summary:
            yield tool_summary_event(tool_summary, self.name)
        yield AgentEvent(
            type=EventType.ERROR,
            agent_name=self.name,
            data="Модель вернула пустой ответ",
            metadata={"model": model},
        )

    async def _interrupted(
        self,
        exc: Exception,
        *,
        collected: str,
        usage: dict,
        model: str,
        tool_summary: dict[str, Any] | None = None,
    ) -> AsyncGenerator[AgentEvent]:
        """Стрим оборвался — отдать собранное, а не потерять его вместе с ошибкой.

        ⚠️ Частичный ответ ЦЕННЕЕ голой ошибки: провайдеру уже заплачено, и человек скорее
        дочитает неполное, чем начнёт заново. Пустой ответ — честная ошибка.
        """
        failure = classify_provider_failure(exc, provider=usage.get("provider"))
        logger.warning("Streamed chat interrupted code=%s", failure.code.value)
        if not collected.strip():
            if tool_summary:
                yield tool_summary_event(tool_summary, self.name)
            yield AgentEvent(
                type=EventType.ERROR,
                agent_name=self.name,
                data="Выполнение завершилось безопасно обработанной ошибкой.",
                metadata={
                    "failure_code": failure.code.value,
                    "category": "provider",
                    "retryable": failure.retryable,
                    "status_family": failure.status_family or "none",
                },
            )
            return
        note = "\n\n_⚠️ Ответ прерван (таймаут провайдера) и может быть неполным._"
        collected += note
        if tool_summary:
            yield tool_summary_event(tool_summary, self.name)
        yield AgentEvent(
            type=EventType.STREAM_CHUNK, agent_name=self.name, data=note, metadata={"model": model}
        )
        yield AgentEvent(
            type=EventType.AGENT_COMPLETE,
            agent_name=self.name,
            data=f"Completed {self.name} (interrupted)",
            metadata={
                "model": model,
                "interrupted": True,
                "failure_code": failure.code.value,
                "token_usage": usage,
                "tool_summary": tool_summary or {},
            },
        )

    async def _run_chat_streamed(
        self, question: str, context: UserContext | None
    ) -> AsyncGenerator[AgentEvent]:
        """Реалтайм-стрим ответа через chat/completions (mws/openrouter).

        Токены отдаются по мере генерации (STREAM_CHUNK), история передаётся
        отдельными репликами — это убирает повторы и игнор текущего вопроса.
        """
        selected_model = await self._resolve_chat_model()
        if not selected_model:
            yield model_unavailable_event(self.name)
            return
        prepared = await prepare_chat_run(
            self,
            question=question,
            context=context,
            model=selected_model,
            execution=require_execution(),
        )
        for event in prepared.events():
            yield event
        state = prepared.start_loop(self)
        run_execution = state.execution
        usage_scope = state.usage_scope
        tool_summary = state.tool_summary
        try:
            async for event in run_streamed_tool_loop(
                state,
                agent_name=self.name,
                stream=stream_chat_completion,
                execute_tool_round=self._execute_tool_round,
                estimate_prompt_tokens=_estimated_prompt_tokens,
            ):
                yield event
        except Exception as exc:
            async for event in self._interrupted(
                exc,
                collected=state.collected,
                usage=_chat_usage(run_execution, usage_scope),
                model=selected_model,
                tool_summary=tool_summary,
            ):
                yield event
            return

        if run_execution.question.waiting or run_execution.question.failed:
            from service.domain.runners.human_question_pause import question_boundary_event

            yield question_boundary_event(
                run_execution, agent_name=self.name, usage=_chat_usage(run_execution, usage_scope)
            )
            return
        if not state.collected.strip():
            if state.tool_cap_hit:
                # Деградируем мягко: модель хотела ещё шаги с инструментами, но лимит
                # раундов исчерпан, а текста она не дала. Голая ошибка тут выглядит как
                # сбой; вместо неё — честное объяснение и предложение переспросить.
                msg = tool_cap_message()
                yield AgentEvent(
                    type=EventType.STREAM_CHUNK,
                    agent_name=self.name,
                    data=msg,
                    metadata={"model": selected_model},
                )
            async for event in self._finish_without_text(
                tool_cap_hit=state.tool_cap_hit,
                usage=_chat_usage(run_execution, usage_scope),
                model=selected_model,
                tool_summary=tool_summary,
            ):
                yield event
            return

        yield tool_summary_event(tool_summary, self.name)
        yield completed_event(
            self.name,
            selected_model,
            _chat_usage(run_execution, usage_scope),
            tool_summary,
        )
