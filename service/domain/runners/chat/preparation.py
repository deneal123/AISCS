"""Prepare one policy-resolved chat run, then activate its streamed loop.

Preparation restores the transcript and selects only pre-authorized tools. It may
use the existing disclosure model/ledger, but never starts the primary model or
executes a tool. Activation is separate: the caller yields preparation events
before opening the chat usage scope and constructing execution state.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from service.domain.capabilities.tools.registry import get_tool_spec
from service.domain.capabilities.tools.spec import ToolSet
from service.domain.execution.context import RunExecutionContext
from service.domain.runners.chat.disclosure import DisclosureUpdate, ToolSelectionController
from service.domain.runners.chat.stream_state import ChatStreamLoopState
from service.domain.runners.chat.tool_loop import _omissions_event, tool_availability_event
from service.domain.runners.chat.tool_state import initial_tool_summary
from service.domain.runners.prompt_budget import prompt_budget_for_execution, prompt_budget_per_run
from service.domain.runners.support import _as_int, _resolve_chat_max_tokens
from service.domain.runners.tool_runtime import ToolCallCache
from service.domain.usage.ledger import UsageKind
from service.events import AgentEvent
from service.schemas.agents import UserContext


class ChatPreparationOwner(Protocol):
    name: str

    def _build_messages(self, question: str, context: UserContext | None) -> list[dict]: ...

    async def _resolve_toolset(self, model: str, context: UserContext | None) -> ToolSet: ...

    def _build_tool_context(self, context: UserContext | None) -> Any: ...


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


def _tool_rounds_for(
    declared: int,
    offered_tools: list,
    *,
    execution: RunExecutionContext | None = None,
) -> int:
    """Bound tool work by trusted task context and post-policy capability metadata.

    IDE gets a hard ceiling of 16; other workspace work retains its eight-round
    minimum. Ordinary chat keeps its declared budget. Names/prefixes neither
    grant file-work budget nor authorize a capability; deadlines and prompt
    budget remain independent, tighter limits.
    """
    from service.domain.execution.context import current_execution

    execution = execution or current_execution()
    if execution and isinstance((execution.resources.workspace_ref or {}).get("ide_context"), dict):
        return max(0, 16 - execution.task.rounds)
    if any(
        spec and spec.source == "workspace"
        for spec in (get_tool_spec(_tool_name(tool)) for tool in offered_tools or [])
    ):
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


@dataclass(frozen=True, slots=True)
class PreparedChatRun:
    """Run inputs owned by preparation; no transport or terminal authority."""

    execution: RunExecutionContext
    messages: list[dict]
    model: str
    context: UserContext | None
    max_tokens: int
    max_continuations: int
    prompt_budget: int
    controller: ToolSelectionController
    disclosure: DisclosureUpdate
    tool_summary: dict[str, Any]

    def events(self) -> Iterator[AgentEvent]:
        yield from self.disclosure.events
        toolset = self.disclosure.toolset
        yield tool_availability_event(toolset, self.controller.agent_name)
        if omissions := _omissions_event(toolset, self.controller.agent_name):
            yield omissions

    def start_loop(self, owner: ChatPreparationOwner) -> ChatStreamLoopState:
        """Activate only after preparation events have been consumed by the caller."""
        from service.domain.runners.harness.continuation import restored_length_continuations

        tool_index = self.controller.tool_index
        tool_ctx = owner._build_tool_context(self.context)
        openai_tools = self.disclosure.toolset.tools
        max_tool_rounds = _tool_rounds_for(
            _as_int(getattr(owner, "max_turns", 4), 4), openai_tools, execution=self.execution
        )
        usage_scope = self.execution.usage.open_scope(kind=UsageKind.CHAT)
        if self.execution.tool_cache is None:
            self.execution.tool_cache = ToolCallCache()
        return ChatStreamLoopState(
            continuations=restored_length_continuations(self.execution),
            execution=self.execution,
            usage_scope=usage_scope,
            messages=self.messages,
            convo=list(self.messages),
            round_messages=list(self.messages),
            openai_tools=openai_tools,
            tool_index=tool_index,
            tool_ctx=tool_ctx,
            disclosure_controller=self.controller,
            tool_summary=self.tool_summary,
            model=self.model,
            max_tokens=self.max_tokens,
            max_continuations=self.max_continuations,
            max_tool_rounds=max_tool_rounds,
            prompt_budget=self.prompt_budget,
            estimated_prompt_spent=self.disclosure.estimated_prompt_tokens,
            context=self.context,
            tool_dedup_mode=_tool_dedup_mode(),
            tool_cache=self.execution.tool_cache,
            tool_choice=self.disclosure.tool_choice,
        )


async def prepare_chat_run(
    owner: ChatPreparationOwner,
    *,
    question: str,
    context: UserContext | None,
    model: str,
    execution: RunExecutionContext,
) -> PreparedChatRun:
    """Restore messages, then disclose from the policy/model/configuration tool set."""
    reference = execution.resources.workspace_ref or {}
    execution.task.active = any(
        isinstance(reference.get(key), dict) for key in ("ide_context", "document_context")
    )
    resumed = execution.question.resumed_messages(model)
    continuation = execution.harness.current.continuation if execution.harness is not None else None
    if resumed is not None:
        messages = resumed
    elif continuation is not None and continuation.messages:
        messages = continuation.conversation()
    else:
        messages = owner._build_messages(question, context)
    max_tokens, max_continuations = _round_limits()
    eligible_toolset = await owner._resolve_toolset(model, context)
    prompt_budget = prompt_budget_for_execution(execution, legacy_limit=prompt_budget_per_run())
    controller = ToolSelectionController(
        eligible_toolset=eligible_toolset,
        question=question,
        agent_name=owner.name,
        context=context,
        preferred_model=model,
        execution=execution,
    )
    disclosure = await controller.select(
        stage=1,
        remaining_prompt_tokens=prompt_budget or None,
    )
    if execution.harness is None or not execution.harness.current.continuation.messages:
        messages = _with_workspace_tool_protocol(messages, disclosure.toolset.tools)
        from service.domain.runners.harness.lessons import with_verified_lessons

        messages = await with_verified_lessons(messages, disclosure.toolset.tools, execution)
    return PreparedChatRun(
        execution=execution,
        messages=messages,
        model=model,
        context=context,
        max_tokens=max_tokens,
        max_continuations=max_continuations,
        prompt_budget=prompt_budget,
        controller=controller,
        disclosure=disclosure,
        tool_summary=initial_tool_summary(disclosure.toolset),
    )
