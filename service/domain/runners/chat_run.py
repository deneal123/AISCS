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
from service.domain.run_context import RunExecutionContext, require_execution
from service.domain.runners.chat_stream_loop import ChatStreamLoopState, run_streamed_tool_loop
from service.domain.runners.chat_terminal import completed_event, tool_cap_message
from service.domain.runners.chat_tool_state import (
    initial_tool_summary,
    model_unavailable_event,
)
from service.domain.runners.prompt_budget import prompt_budget_per_run
from service.domain.runners.support import _as_int, _resolve_chat_max_tokens
from service.domain.runners.tool_disclosure_state import ToolSelectionController
from service.domain.runners.tool_loop import (
    ToolRoundMixin,
    _omissions_event,
    tool_availability_event,
    tool_summary_event,
)
from service.domain.usage_ledger import UsageKind, UsageScope
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext
from service.shared.token_budget import estimate_tokens

logger = logging.getLogger(__name__)


def _round_limits() -> tuple[int, int]:
    """Потолок токенов на вызов и число авто-продолжений.

    Оба читаются через админ-снимок, поэтому вынесены из горячей функции: чтение настроек
    к её теме не относится и мешало видеть цикл целиком.
    """
    from service.settings import config as _config
    from service.shared.agent_settings import runtime_settings

    return (
        _resolve_chat_max_tokens(),
        _as_int(
            runtime_settings.get_agents(
                "chat_max_continuations", _config.agents.chat_max_continuations
            ),
            2,
        ),
    )


def _tool_dedup_mode() -> str:
    """Read the per-run rollout mode from the backend settings snapshot."""
    from service.settings import config as _config
    from service.shared.agent_settings import runtime_settings

    mode = str(
        runtime_settings.get_agents("tool_dedup_mode", _config.agents.tool_dedup_mode) or "observe"
    ).lower()
    return mode if mode in {"off", "observe", "enforce"} else "observe"


def _compact_system_after_workspace_tool(system: str, context: UserContext | None) -> str:
    """Не пересылать карту репозитория после первого workspace-инструмента.

    Карта нужна модели только чтобы выбрать первый `ws_*` вызов. Далее её заменяют
    результаты `ws_list`/`ws_grep`/`ws_read`; повторная отправка карты раздувает цену
    каждого следующего раунда и не добавляет фактов.
    """
    system_context = str(getattr(context, "system_context", "") or "")
    if not system_context or (
        "# Graph Report" not in system_context and "# Файлы архива (" not in system_context
    ):
        return system
    prefix = system.removesuffix(system_context).rstrip()
    if prefix == system.rstrip():
        return system
    return (
        f"{prefix}\n\n## Контекст архива\n"
        "Карта репозитория уже использована для выбора инструментов. "
        "Дальше опирайся на результаты workspace-инструментов; при необходимости "
        "исследуй нужные файлы ими."
    )


def _estimated_prompt_tokens(messages: list[dict], tools: list | None) -> int:
    """Консервативная оценка исходящего prompt с JSON схемами инструментов."""
    import json

    return estimate_tokens(json.dumps(messages, ensure_ascii=False, default=str)) + estimate_tokens(
        json.dumps(tools or [], ensure_ascii=False, default=str)
    )


# Раундов при работе с файлами. Осмысленная цепочка чтения кода — посмотреть дерево, найти
# место, прочитать файл — это УЖЕ три, а вопрос почти всегда касается двух-трёх файлов.
FILE_WORK_TOOL_ROUNDS = 8

_FILE_TOOL_PREFIX = "ws_"

_WORKSPACE_TOOL_PROTOCOL = """

Работа с функциями рабочего места:
- Функции ws_* реально доступны в этом запросе.
- Если пользователь прямо просит прочитать, создать или изменить файл, сначала обязательно
  вызови подходящую функцию ws_* и дождись её результата.
- Не заменяй вызов функции уточняющим вопросом, если путь и требуемое содержимое уже указаны.
- Не утверждай, что файл прочитан или изменён, пока функция не вернула успешный результат.
"""


def _tool_name(item) -> str:
    """Имя инструмента из того, что РЕАЛЬНО лежит в наборе.

    🔴 НАБОР УЖЕ СЕРИАЛИЗОВАН. `_resolve_toolset` возвращает `_tools_to_openai(...)`, то
    есть словари `{"type": "function", "function": {"name": …}}`, а не объекты `FunctionTool`.
    Первая редакция правила читала `getattr(item, "name", "")` — у словаря это пустая
    строка, поэтому файловые инструменты не распознавались НИ РАЗУ и лимит раундов не
    поднимался вообще.

    ⚠️ Дефект пережил и стражей, и живой замер. Тест подсовывал `SimpleNamespace(name=…)` —
    форму, которую я ПРЕДПОЛОЖИЛ вместо того, чтобы посмотреть; замер на gpt-4o не краснел,
    потому что та укладывалась в четыре раунда. Нашёл человек: на GigaChat-2-Max агент
    прочитал файлы (`ws_grep`, `ws_grep`, `ws_list`, `ws_read`) и получил «не удалось
    довести задачу до ответа за отведённое число шагов» — 5804 кредита за ничего.

    ⚠️ Поддерживаем ОБА вида: словарь (боевой путь) и объект с `.name` (прямые вызовы и
    тесты). Требовать один — значит снова угадывать, какой именно придёт.
    """
    if isinstance(item, dict):
        function = item.get("function")
        if isinstance(function, dict):
            return str(function.get("name") or "")
        return str(item.get("name") or "")
    return str(getattr(item, "name", "") or "")


def _tool_rounds_for(declared: int, offered_tools: list) -> int:
    """Сколько раундов инструментов дать этому прогону.

    🔴 ЧЕТЫРЁХ РАУНДОВ НА РАБОТУ С ФАЙЛАМИ НЕ ХВАТАЕТ, и замер это показал дважды. Оба
    прогона на живом стенде (архив `requests` развёрнут в песочнице, вопрос «покажи код
    функции и объясни построчно») кончились одинаково: модель истратила раунды на пробные
    вызовы и человек получил «Не удалось довести задачу до ответа за отведённое число
    шагов». Во второй раз она успела написать «сейчас я найду и открою код функции» — и
    ровно на этой фразе раунды кончились.

    Четыре — верная цена для обычного чата: там инструмент зовут один раз, а каждый раунд
    переотправляет весь растущий диалог. Но при выданных файловых инструментах минимальная
    осмысленная цепочка (`ws_list` → `ws_grep` → `ws_read`) занимает три, и на ответ
    остаётся один — то есть ЛЮБАЯ неудачная проба роняет прогон целиком. Пять вызовов LLM с
    полным промптом и нулевой результат дороже восьми раундов, доводящих задачу до конца.

    ⚠️ Поднимаем ТОЛЬКО когда файловые инструменты действительно выданы: обычный чат
    (большинство запросов) остаётся на прежней цене. Гейт при этом уже отработал — набор
    здесь окончательный, и догадываться о нём не нужно.
    """
    if any(_tool_name(t).startswith(_FILE_TOOL_PREFIX) for t in offered_tools or []):
        return max(declared, FILE_WORK_TOOL_ROUNDS)
    return declared


def _with_workspace_tool_protocol(messages: list[dict], offered_tools: list) -> list[dict]:
    """Tell the model how to use an actually offered workspace capability.

    The function set remains the authorization source; this text cannot enable a tool.
    Keeping the instruction conditional also avoids asking models without workspace access
    to perform an impossible action.  A detached list prevents caller-owned history from
    being mutated when a round is prepared.
    """

    if not any(_tool_name(tool).startswith(_FILE_TOOL_PREFIX) for tool in offered_tools or []):
        return messages
    prepared = [dict(message) for message in messages]
    for message in prepared:
        if message.get("role") == "system":
            message["content"] = str(message.get("content") or "") + _WORKSPACE_TOOL_PROTOCOL
            return prepared
    return [{"role": "system", "content": _WORKSPACE_TOOL_PROTOCOL.strip()}, *prepared]


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
        messages = self._build_messages(question, context)
        max_tokens, max_continuations = _round_limits()
        # Инструменты уходят в запрос только если модель их умеет: провайдеры без
        # поддержки отвечают 400 на неизвестное поле `tools`. Отобранное НЕ пропадает —
        # уезжает событием, иначе «поиска не было» неотличимо от «модель им не воспользовалась».
        # Policy/model/configuration gates run first. Progressive disclosure is then only
        # allowed to reduce this already-authorized set, never to grant a new capability.
        eligible_toolset = await self._resolve_toolset(selected_model, context)
        prompt_budget = prompt_budget_per_run()
        run_execution = require_execution()
        disclosure_controller = ToolSelectionController(
            eligible_toolset=eligible_toolset,
            question=question,
            agent_name=self.name,
            context=context,
            preferred_model=selected_model,
            execution=run_execution,
        )
        disclosure = await disclosure_controller.select(
            stage=1,
            remaining_prompt_tokens=prompt_budget or None,
        )
        toolset = disclosure.toolset
        openai_tools = toolset.tools
        messages = _with_workspace_tool_protocol(messages, openai_tools)
        tool_summary: dict[str, Any] = initial_tool_summary(toolset)
        for event in disclosure.events:
            yield event
        yield tool_availability_event(toolset, self.name)
        if omissions := _omissions_event(toolset, self.name):
            yield omissions
        # Include run-scoped MCP tools too. The primary model may see only a selected
        # tier, while the executor still resolves the same pre-authorized candidate set.
        tool_index = disclosure_controller.tool_index
        tool_ctx = self._build_tool_context(context)
        max_tool_rounds = _tool_rounds_for(_as_int(getattr(self, "max_turns", 4), 4), openai_tools)
        usage_scope = run_execution.usage.open_scope(kind=UsageKind.CHAT)
        if run_execution.tool_cache is None:
            from service.domain.runners.tool_execution import ToolCallCache

            run_execution.tool_cache = ToolCallCache()
        state = ChatStreamLoopState(
            execution=run_execution,
            usage_scope=usage_scope,
            messages=messages,
            convo=list(messages),
            round_messages=list(messages),
            openai_tools=openai_tools,
            tool_index=tool_index,
            tool_ctx=tool_ctx,
            disclosure_controller=disclosure_controller,
            tool_summary=tool_summary,
            model=selected_model,
            max_tokens=max_tokens,
            max_continuations=max_continuations,
            max_tool_rounds=max_tool_rounds,
            prompt_budget=prompt_budget,
            estimated_prompt_spent=disclosure.estimated_prompt_tokens,
            context=context,
            tool_dedup_mode=_tool_dedup_mode(),
            tool_cache=run_execution.tool_cache,
            tool_choice=disclosure.tool_choice,
        )
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
