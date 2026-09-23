"""Web search sub-agent."""

import asyncio
import logging
from collections.abc import AsyncGenerator

from service.domain.capabilities.agent_spec import COST_PAID, AgentSpec
from service.domain.llm_response import first_message_content
from service.domain.model_runtime import invoke_model_call, record_estimated_model_call
from service.domain.run_context import RunExecutionContext, require_execution
from service.domain.subagents.base import BaseSubAgent
from service.domain.subagents.utils import pick_answer_model
from service.domain.usage_ledger import UsageKind
from service.domain.usage_tracking import build_token_usage_meta
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext
from service.shared.token_budget import estimate_tokens

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "Выполняй веб-поиск, извлекай ключевые факты и синтезируй практичный ответ. "
    "Всегда отделяй подтверждённые факты от предположений и указывай источники."
)

_NO_SOURCES_REPLY = (
    "По внешнему поиску сейчас не удалось получить источники "
    "(таймаут или блокировка поиска).\n\n"
    "Что можно сделать:\n"
    "1) Уточнить запрос (добавить период/регион).\n"
    "2) Повторить через 1-2 минуты.\n"
    "3) Прислать 2-3 ссылки — я сразу сделаю выжимку по ним.\n"
)

# ⚠️ ОДНО ПРАВИЛО НА ОБА ПУТИ СИНТЕЗА (здесь и в tools/deep_research). Держим текст
# идентичным: разъедутся — один режим начнёт выдавать вводные пользователя за факт, а
# другой нет. Живая жалоба: на запрос «сделай досье, X работает в банке неофициально как
# вендор» отчёт подал это утверждение как установленный факт о названном лице и построил
# на нём раздел «репутационные риски» — при том что источники ничего подобного не
# содержали. Досье на конкретных людей с недоказанными утверждениями — риск и
# репутационный, и правовой.
_SOURCE_DISCIPLINE = (
    "РАЗДЕЛЯЙ «что сказал пользователь» и «что подтверждено источниками». Утверждения из "
    "запроса пользователя — это ВВОДНЫЕ ДЛЯ ПРОВЕРКИ, а не установленные факты. Фактом "
    "считай только то, что прямо подтверждают источники. Чего в источниках нет — обозначай "
    "как непроверенное («в источниках не подтверждается»), НЕ пересказывай как достоверное "
    "и НЕ строй на этом выводы, оценки или «риски». Про конкретных людей особенно: не "
    "приписывай названному лицу свойств, которых нет в источниках, даже если о них "
    "говорилось в запросе.\n"
)

_SYNTHESIS_PROMPT = (
    "Ты аналитик с доступом к веб-данным. "
    "Используй ТОЛЬКО предоставленные результаты поиска как основную базу фактов.\n"
    + _SOURCE_DISCIPLINE
    + "Отвечай в контексте диалога (учитывай предыдущие реплики), а не буквально.\n"
    "Требования к ответу:\n"
    "1) Краткий вывод в начале (2-4 пункта).\n"
    "2) Затем структурированные детали с подзаголовками.\n"
    "3) Если данных мало или есть противоречия — явно это отметь.\n"
    "4) В конце добавь блок 'Источники' со ссылками.\n"
    "Пиши на языке пользователя и используй Markdown.\n"
)

# Запас поверх самого медленного провайдера: дедлайн синтеза обязан быть СТРОГО больше
# транспортного, иначе он срабатывает раньше, чем провайдер успевает ответить.
_SYNTHESIS_DEADLINE_MARGIN_SEC = 15.0

_SYNTHESIS_TIMEOUT_REPLY = (
    "Не удалось дождаться итоговой генерации модели (таймаут). Ниже — собранные данные:\n\n"
)


def _format_search_data(results: list[dict], pages: list[dict]) -> str:
    """Собрать найденное в текстовый блок для модели: список ссылок + тела страниц."""
    parts = ["## Результаты веб-поиска:\n"]
    for i, r in enumerate(results, 1):
        parts.append(f"\n{i}. **{r.get('title', '')}** ({r.get('url', '')})\n")
        parts.append(f"   {r.get('snippet', '')}\n")
    for p in pages:
        parts.append(f"\n### Содержимое: {p.get('title', '')}\n{p.get('content', '')[:1500]}\n")
    return "".join(parts)


class WebSearchAgent(BaseSubAgent):
    """Specialized agent for web-search augmented answers."""

    def __init__(self, model_settings: dict):
        super().__init__(
            name="web_search",
            instructions=_INSTRUCTIONS,
            model_settings=model_settings,
        )

    async def _synthesize(
        self,
        user_input: str,
        context: UserContext,
        search_data: str,
        model: str,
        execution: RunExecutionContext | dict,
    ) -> str:
        """Свести найденное в ответ. Таймаут не ошибка: отдаём сырые данные как есть."""
        from service.domain.client import create_chat_completion

        execution = require_execution(
            execution if isinstance(execution, RunExecutionContext) else None
        )

        # Подмешиваем недавнюю историю диалога — чтобы синтез отвечал по теме
        # разговора (follow-up «по этой теме»), а не по буквальному тексту.
        history = [
            {"role": m.get("role", "user"), "content": str(m.get("content", ""))}
            for m in list(getattr(context, "history_messages", None) or [])[-6:]
            if str(m.get("content", "")).strip()
        ]
        # Собранный пайплайном контекст пользователя (память/знания/план) — раньше синтез
        # его не видел, и follow-up «сравни это с тем, что онлайн» уходил в веб без
        # загруженного документа. Обрезан, чтобы не вытеснять результаты поиска.
        # Личность влияет на СТИЛЬ сведения найденного и на критерии доверия источникам,
        # но не на сами результаты: поиск уже отработал, подмешивать специализацию в
        # выдачу поздно и незачем.
        synthesis_prompt = self.persona_wrap(_SYNTHESIS_PROMPT, "search.synthesis")
        synthesis_prompt = self.persona_wrap(synthesis_prompt, "search.sources")
        system_content = synthesis_prompt + "\n" + search_data
        extra_ctx = self.extra_user_context(context)
        if extra_ctx:
            system_content += "\n\n## Контекст пользователя (память/знания)\n" + extra_ctx

        # ⚠️ ДЕДЛАЙН ВЫВОДИМ ИЗ ТАЙМАУТОВ ПРОВАЙДЕРОВ, А НЕ ЗАДАЁМ ЧИСЛОМ. Здесь стояло
        # `timeout=20` при `routerai_timeout_sec=45` и дефолте openai 60: внешний срок был
        # жёстче транспортного, то есть на медленном провайдере ответ был невозможен ПО
        # ПОСТРОЕНИЮ. Живая жалоба: 8 шагов, 52 секунды, «не удалось дождаться итоговой
        # генерации» и сырая выдача вместо ответа — при том что вызов оплачен.
        #
        # Запас поверх максимума нужен на сам обмен (постановка запроса, сеть, разбор): без
        # него дедлайн совпадает с транспортным, и мы срезаем провайдера ровно в тот
        # момент, когда он имеет право ответить.
        from service.domain.client.registry import max_provider_timeout_sec

        deadline = max_provider_timeout_sec() + _SYNTHESIS_DEADLINE_MARGIN_SEC
        try:
            result = await asyncio.wait_for(
                invoke_model_call(
                    create_chat_completion,
                    messages=[
                        {"role": "system", "content": system_content},
                        *history,
                        {"role": "user", "content": user_input},
                    ],
                    model=model,
                    kind=UsageKind.RESEARCH_SYNTHESIS,
                    execution=execution,
                    temperature=0.5,
                    max_tokens=1500,
                ),
                timeout=deadline,
            )
        except TimeoutError:
            logger.warning("LLM synthesis timeout in web_search agent")
            # ⚠️ ВЫЗОВ ОПЛАЧЕН, ХОТЯ ОТВЕТА НЕТ. `wait_for` отменяет корутину на НАШЕЙ
            # стороне — провайдер запрос принял и промпт обработал, а промпт здесь
            # дорогой: в него уложены ВСЕ результаты поиска. Раньше `accumulate_usage`
            # строкой ниже просто не достигался, и вызов уходил бесплатным.
            #
            # Только ОЦЕНКА и только PROMPT: объекта ответа не существует, считать
            # нечего, а completion пользователь не получил — брать за него деньги было
            # бы платой за то, чего он не видел. Оценка занижена намеренно.
            record_estimated_model_call(
                model=model,
                kind=UsageKind.RESEARCH_SYNTHESIS,
                prompt_tokens=estimate_tokens(system_content),
                execution=execution,
            )
            return f"{_SYNTHESIS_TIMEOUT_REPLY}{search_data}"

        return first_message_content(result.response) or ""

    async def process(self, user_input: str, context: UserContext) -> AsyncGenerator[AgentEvent]:
        yield self.start_event("Запускаю веб-поиск")

        safety = await self.evaluate_input_safety(user_input)
        if safety["sensitive"]:
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=self.name,
                data="⚠️ Чувствительная тема: показываю только безопасный и нейтральный анализ.",
                metadata=safety["meta"],
            )
        if safety["blocked"]:
            yield AgentEvent(
                type=EventType.ERROR,
                agent_name=self.name,
                data=safety["message"],
                metadata=safety["meta"],
            )
            yield self.complete_event("Веб-поиск остановлен guardrails")
            return

        yield AgentEvent(
            type=EventType.TOOL_CALL_START,
            agent_name=self.name,
            data="Выполняю поиск в интернете...",
        )

        execution = require_execution()
        usage_cursor = execution.usage.cursor()
        try:
            from service.domain.client import list_qualified_models
            from service.domain.subagents.context_query import (
                build_standalone_query,
            )
            from service.domain.tools.web_search import parse_url, search_budget_sec, web_search

            models = await list_qualified_models()
            model = pick_answer_model(models, self.preferred_model())
            # Раскрываем follow-up («найди инфо по этой теме») в самостоятельный
            # запрос по истории диалога — иначе поиск уходит в веб буквально.
            search_query = await build_standalone_query(
                user_input,
                context,
                model,
                execution=execution,
            )

            try:
                results = await asyncio.wait_for(
                    web_search(search_query, num_results=5), timeout=search_budget_sec()
                )
            except TimeoutError:
                logger.warning("web_search failed code=timeout")
                results = []

            yield AgentEvent(
                type=EventType.TOOL_CALL_COMPLETE,
                agent_name=self.name,
                data=f"Найдено результатов: {len(results)}",
                metadata={"result_count": len(results), "status": "completed"},
            )

            if not results:
                async for chunk_event in self.stream_text_chunks(_NO_SOURCES_REPLY):
                    yield chunk_event
                yield self.complete_event("Веб-поиск завершён (без внешних источников)")
                return

            # ⚠️ Две страницы читаются ПАРАЛЛЕЛЬНО. Они независимы, а шли по одной: два
            # таймаута по 8 с складывались в 16 с ожидания на ровном месте.
            async def _read(url: str) -> dict:
                try:
                    return await asyncio.wait_for(parse_url(url, max_chars=2000), timeout=8)
                except TimeoutError:
                    logger.debug("web page read timeout", extra={"failure_code": "timeout"})
                    return {}

            urls = [r.get("url", "") for r in results[:2] if r.get("url")]
            pages = await asyncio.gather(*(_read(u) for u in urls)) if urls else []

            search_data = _format_search_data(results, [p for p in pages if p.get("content")])

            reply = (
                await self._synthesize(user_input, context, search_data, model, execution)
                if model
                else search_data
            )
            async for chunk_event in self.stream_text_chunks(reply):
                yield chunk_event
        except Exception:
            logger.error("Web search failed code=internal")
            yield self.error_event("Веб-поиск завершился безопасной ошибкой.")

        usage_view = execution.usage.project_since(usage_cursor)
        yield self.complete_event("Веб-поиск завершён", build_token_usage_meta(usage_view))


SPEC = AgentSpec(
    name="web_search",
    label_ru="веб-поиск",
    build=WebSearchAgent,
    billing_name="web_search",
    cost_class=COST_PAID,
    prompt_hint=(
        "человек ЯВНО просит найти в интернете или спрашивает про сегодняшнее\n"
        "  состояние мира (курс, погода, новости, «что сейчас», события этого года)."
    ),
)
