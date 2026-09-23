"""Base classes for agent implementations."""

import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from types import SimpleNamespace

from service.domain import persona
from service.domain.capabilities.tool_registry import resolve_toolset
from service.domain.capabilities.tool_spec import ToolSet
from service.domain.client import (
    is_chat_capable,
    list_qualified_models,
)
from service.domain.runners import ChatRunMixin, SdkRunMixin
from service.domain.runners.support import (
    _tools_to_openai,
)
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext
from service.shared.token_budget import estimate_tokens, trim_text_to_tokens

logger = logging.getLogger(__name__)


def _agent_flag(name: str, default):
    """Runtime-настройка агентов из админ-overlay (fail-safe → дефолт из config).

    Тот же тонкий хелпер, что в `application/processor_steps.py`: читать overlay «своим»
    способом в каждом файле значит однажды прочитать мимо него и получить декоративный
    тумблер в панели.
    """
    from service.shared.agent_settings import runtime_settings

    return runtime_settings.get_agents(name, default)


def _instructions_max_chars() -> int:
    """Потолок базовых инструкций агента.

    ⚠️ Раньше это был литерал `3000` прямо в срезе, и обрезка происходила МОЛЧА. Значение
    вынесено в настройку (дефолт тот же, поведение байт-в-байт) и читается через overlay:
    ключ, объявленный в админке и читаемый в обход overlay, — декоративный тумблер.

    ⚠️ `_agent_flag` зовётся ЗДЕСЬ, а не через свою обёртку-хелпер: офлайн-гейт контракта
    ищет чтение overlay по ИМЕНИ вызова (`get_agents`/`_agent_flag`/`_flag`) и допускает
    прямое `config.agents.X` только рядом с ним. Промежуточная обёртка прячет чтение от
    гейта, и он справедливо объявляет ключ мёртвым.
    """
    from service.settings import config

    try:
        return int(_agent_flag("instructions_max_chars", config.agents.instructions_max_chars))
    except (TypeError, ValueError):
        return int(config.agents.instructions_max_chars)


def _persona_max_tokens() -> int:
    """Бюджет секции личности — СВОЙ, а не доля бюджета инструкций."""
    from service.settings import config

    try:
        return int(_agent_flag("persona_max_tokens", config.agents.persona_max_tokens))
    except (TypeError, ValueError):
        return int(config.agents.persona_max_tokens)


# Подсказка модели для бесшовного авто-продолжения ответа, обрезанного по лимиту
# токенов (finish_reason == "length").


class BaseAgent(ABC):
    """Abstract base class for all agents.

    All agents must implement process() which yields AgentEvent objects.
    """

    def __init__(self, name: str, instructions: str, model_settings: dict):
        self.name = name
        self.instructions = instructions
        self.model_settings = model_settings

    @abstractmethod
    async def process(self, user_input: str, context: UserContext) -> AsyncGenerator[AgentEvent]:
        """Main entry point for agent processing.

        Must yield AgentEvent objects that describe what the agent is doing.
        """
        pass


class SimpleStreamingAgent(BaseAgent, SdkRunMixin, ChatRunMixin):
    """Agent that streams responses directly with optional tool use.

    Best for: Q&A, conversational agents that need quick responses.
    Tools are allowed but limited to prevent loops.
    """

    def __init__(
        self,
        name: str,
        instructions: str,
        model_settings: dict,
        tools: list = None,
        input_guardrails: list = None,
        output_guardrails: list = None,
        max_turns: int = 6,
    ):
        super().__init__(name, instructions, model_settings)
        self.tools = tools or []
        self.input_guardrails = input_guardrails or []
        self.output_guardrails = output_guardrails or []
        self.max_turns = max_turns

    async def _input_guardrail_block(self, user_input: str) -> AgentEvent | None:
        """Вход-гардрейлы для ЖИВОГО стрим-пути (_run_chat_streamed).

        SDK-декораторы @input_guardrail срабатывают только на SDK-пути Runner'а —
        а для mws/openrouter/gigachat/routerai (все рабочие провайдеры) мы уходим в
        _run_chat_streamed, минуя их. Из-за этого самый нагруженный агент (general)
        на живом трафике был БЕЗ вход-фильтра (аудит P0.4). Зовём сырые guardrail-
        функции напрямую (как evaluate_input_safety у субагентов). Возвращаем ERROR-
        событие при блокировке, иначе None. Помечаем guardrail_block=True, чтобы
        ре-роут (run_with_reroute) не обошёл блок, отдав запрос агенту без гардрейлов.
        Fail-open: сбой самой проверки не должен ронять запрос.
        """
        from service.domain.guardrails import (
            check_appropriate_language,
            check_forbidden_topics,
        )

        text = str(user_input or "")
        try:
            abusive = await check_appropriate_language.guardrail_function(None, None, text)
            forbidden = await check_forbidden_topics.guardrail_function(None, None, text)
        except Exception:
            # ⚠️ Fail-open сознательный, но больше не молча: сломанный гардрейл положил бы
            # сервис целиком, а на DEBUG его отказ был неотличим от штатного «пропускаю».
            logger.warning("input guardrail failed code=internal; request allowed")
            return None
        if not (abusive.tripwire_triggered or forbidden.tripwire_triggered):
            return None
        return AgentEvent(
            type=EventType.ERROR,
            agent_name=self.name,
            data=(
                "Запрос затрагивает небезопасную тему. Переформулируйте вопрос "
                "в безопасном и образовательном формате."
            ),
            metadata={
                "failure_code": "policy",
                "category": "internal",
                "retryable": False,
                "status_family": "none",
            },
        )

    async def process(self, user_input: str, context: UserContext) -> AsyncGenerator[AgentEvent]:
        """Stream response with optional tool calls."""
        yield AgentEvent(
            type=EventType.AGENT_START, agent_name=self.name, data=f"Starting {self.name}"
        )

        # Вход-гардрейлы ДО любой работы с моделью — единой точкой для обоих путей
        # (живого chat-стрима и SDK). На живом пути SDK-декораторы не срабатывают, и
        # без этого гейта general отвечал бы на небезопасный вход без фильтра.
        block = await self._input_guardrail_block(user_input)
        if block is not None:
            yield block
            yield AgentEvent(
                type=EventType.AGENT_COMPLETE,
                agent_name=self.name,
                data=f"{self.name} остановлен guardrails",
                metadata={"failure_code": "policy"},
            )
            return

        # ⚠️ Причина гейта — ФЕЙЛОВЕР, а не Responses (в Responses SDK давно не ходит).
        # `stream_chat_completion` умеет то, чего у SDK-пути нет: перебор провайдеров до
        # первой дельты, пиннинг между раундами tool-loop и per-provider `include_usage`.
        # SDK работает с ОДНИМ клиентом: уведи сюда трафик — и отказоустойчивость исчезнет
        # молча. Плюс GigaChat под SDK игнорирует канонические `tools`.
        from service.domain.client.provider_compat import active_provider_name
        from service.domain.run_context import require_current_execution

        execution = require_current_execution()
        active_provider = (
            execution.provider_snapshot.active_provider
            if execution.provider_snapshot is not None
            else active_provider_name()
        )
        if active_provider in ("mws", "openrouter", "gigachat", "routerai"):
            async for event in self._run_chat_streamed(user_input, context):
                yield event
            return

        async for event in self._run_sdk_streamed(user_input, context):
            yield event

    # Пары «что заменить → на что» в базовых инструкциях, ДЕЙСТВУЮЩИЕ ТОЛЬКО при активной
    # личности. Пусто у всех агентов, кроме `general`: у остальных базовый промпт задаёт
    # не стиль ответа пользователю, а рабочую процедуру, и уступать личности ему нечего.
    persona_overrides: tuple[tuple[str, str], ...] = ()

    def _base_instructions(self) -> str:
        """Инструкции агента с учётом того, что часть из них личность ЗАМЕЩАЕТ.

        Замена, а не дописывание: строки про тон и структуру ответа взаимоисключающи по
        природе, и приписанная следом секция их не перекрывает — она проигрывает
        (см. `PERSONA_OVERRIDES` в `subagents/general.py`).

        Гейт по `is_empty`, а НЕ по непустоте секции: секция бывает непустой и без
        активной личности — ровно на том ходе, когда личность сняли. Замещать базовый
        стиль там нечем и незачем.
        """
        base = str(self.instructions or "")
        if self.persona_overrides and not persona.current().is_empty:
            for old, new in self.persona_overrides:
                base = base.replace(old, new)
        return base[: _instructions_max_chars()]

    def fixed_prompt_tokens(self, context: UserContext | None = None) -> int:
        """Сколько токенов агент шлёт В ЛЮБОМ СЛУЧАЕ, ещё до собранного контекста.

        🔴 ЭТО ЧИСЛО ОТСУТСТВОВАЛО В ОТЧЁТЕ О КОНТЕКСТЕ, И ИМЕННО В НЁМ БЫЛА ЛОЖЬ.
        Ассемблер считал только собранные СЕКЦИИ (запрос, история, вложения…), а базовые
        инструкции, секция личности и схемы инструментов в `used` не входили вовсе.
        Замер на пустом треде: отчёт показывал 14 токенов при реальном промпте 1123 —
        кольцо занятости рисовало 0% там, где уже потрачено больше килотокена.

        Считается из ТЕХ ЖЕ кусков, что уходят в `messages[0]` и в поле `tools`, а не
        отдельным подсчётом: два независимых счётчика ровно так и разъехались.
        """
        parts = [self._base_instructions(), persona.current().section()]
        if self.tools:
            # Схемы инструментов едут не в тексте промпта, а полем `tools` — но окно
            # модели занимают наравне с ним, и на коротком диалоге это самая крупная
            # часть после инструкций (замер: 416 из 1123 токенов).
            try:
                parts.append(
                    json.dumps(
                        _tools_to_openai(self._applicable_tools(context)), ensure_ascii=False
                    )
                )
            except Exception:  # noqa: BLE001 — схемы не сериализуются: считаем без них
                logger.debug("tool schema estimation failed code=internal")
        return sum(estimate_tokens(p) for p in parts if p)

    def _compose_system_instructions(self, context: UserContext | None) -> str:
        """System-инструкции агента + СПЕЦИАЛИЗАЦИЯ + системный контекст.

        ⚠️ У КАЖДОЙ ЧАСТИ СВОЙ БЮДЖЕТ. Раньше здесь стояла одна слепая обрезка
        `instructions[:3000]`. Секция личности приписывается ПОСЛЕ неё и режется отдельно,
        поэтому вытеснить инструкции агента она не может конструктивно, а не по
        договорённости. Обратное тоже верно: длинные инструкции не съедают личность.

        Личность идёт ОТДЕЛЬНОЙ ИМЕНОВАННОЙ СЕКЦИЕЙ, а не вплетается в базовый промпт:
        так базовый промпт остаётся диффабельным (регрессия личности не маскируется под
        регрессию агента), а страж может найти секцию по заголовку.

        Без активной личности строка собирается ровно как прежде — БАЙТ В БАЙТ.
        """
        parts = [self._base_instructions()]

        section = persona.current().section()
        if section:
            parts.append(trim_text_to_tokens(section, _persona_max_tokens()))

        system_context = getattr(context, "system_context", None) if context else None
        if system_context:
            parts.append(str(system_context))
        return "\n\n".join(parts)

    def _build_input_items(self, question: str, context: UserContext | None) -> list[dict]:
        """История как реплики + текущий вопрос (без system — он в instructions)."""
        items: list[dict] = []
        history = (getattr(context, "history_messages", None) or []) if context else []
        for message in history:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")
            if role in ("user", "assistant", "system") and content:
                items.append({"role": role, "content": content})
        items.append({"role": "user", "content": str(question or "")})
        return items

    def _build_messages(self, question: str, context: UserContext | None) -> list[dict]:
        """Полный messages[] для chat/completions: system + история + текущий вопрос."""
        return [
            {"role": "system", "content": self._compose_system_instructions(context)},
            *self._build_input_items(question, context),
        ]

    async def _resolve_chat_model(self) -> str | None:
        selected_model = None
        if isinstance(self.model_settings, dict):
            selected_model = self.model_settings.get("model")
        if self._is_blocked_chat_model(selected_model):
            logger.warning("Blocked non-chat model in chat path: %s", selected_model)
            selected_model = None
        if not selected_model:
            models = await list_qualified_models()
            selected_model = self._pick_chat_capable_model(models)
        return selected_model

    def _applicable_tools(self, context: UserContext | None) -> list:
        """Инструменты, которым в этом запросе есть с чем работать.

        Замер: analyze_data 227 токенов, search_knowledge_graph 192 из 781 на все пять —
        и уезжало это каждым сообщением, включая «привет».
        """
        return resolve_toolset(self.tools, context).tools

    async def _resolve_toolset(self, model: str, context: UserContext | None = None) -> ToolSet:
        """Что уходит модели и что НЕ уходит — с причиной на каждый отказ.

        Без гейта по способностям модели провайдеры без function-calling (часть
        RouterAI/GigaChat) вернут 400 на неизвестное поле `tools`, и ответ упадёт целиком.

        🔴 Три состояния, а не два. «Модель не умеет» и «мы не смогли выяснить» дают
        ОДИНАКОВЫЙ пустой список, но означают разное: первое штатно, второе значит, что
        сломан каталог и человек получит уверенный ответ по памяти вместо поиска. Поэтому
        различие переносится наружу причиной отказа, а не остаётся строкой в логе.
        """
        if not self.tools:
            return ToolSet()
        from service.shared.model_catalog import model_supports_tools

        try:
            supports: bool | None = await model_supports_tools(model)
        except Exception:  # noqa: BLE001
            logger.warning("tool capability catalog failed code=unavailable")
            supports = None
        if supports is False:
            logger.debug("Model %s has no tool support — streaming without tools", model)
        resolved = resolve_toolset(self.tools, context, model_supports=supports)
        return ToolSet(tools=_tools_to_openai(resolved.tools), omissions=resolved.omissions)

    def _build_tool_context(self, context: UserContext | None):
        """RunContextWrapper для исполнителей инструментов (тот же контракт, что на
        SDK-пути: `ctx.context` — словарь с user_id/thread_id/input_type)."""
        from service.domain.run_context import prompt_safe_context_payload

        payload = prompt_safe_context_payload(context)
        try:
            from agents import RunContextWrapper

            return RunContextWrapper(payload)
        except Exception:  # noqa: BLE001 — SDK недоступен: лёгкая заглушка того же вида
            return SimpleNamespace(context=payload)

    @staticmethod
    def _is_blocked_chat_model(model_id: str | None) -> bool:
        # Единый источник правды о «чат-пригодности» — registry.is_chat_capable
        # (полный список маркеров: эмбеддеры/аудио/картинки/модерация). Раньше здесь
        # был свой усечённый список (только эмбеддеры), из-за чего аудио/картиночная
        # модель могла проскочить как чат-модель.
        return bool(str(model_id or "").strip()) and not is_chat_capable(str(model_id))

    @staticmethod
    def _pick_chat_capable_model(models: list[str]) -> str | None:
        """Выбрать модель для chat/completions: фильтр — единый is_chat_capable,
        предпочтение — известным текстовым семействам."""
        filtered = [m for m in (models or []) if is_chat_capable(m)]
        if not filtered:
            filtered = list(models or [])
        text_re = re.compile(
            r"(gpt|qwen|llama|mistral|deepseek|yi|phi|glm|kimi|instruct|chat|alpha)", re.I
        )
        return next((m for m in filtered if text_re.search(m)), filtered[0] if filtered else None)
