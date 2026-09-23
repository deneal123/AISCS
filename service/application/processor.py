"""Main entry point for agent system — unified streaming processor."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

from service.application.orchestrator import Orchestrator
from service.application.processor_steps import ProcessorStepsMixin, _agent_flag
from service.domain.pipeline.error_handling import build_processing_error_event
from service.domain.pipeline.event_stream import EventSequencer
from service.domain.pipeline.execution_plan import execute_steps, run_with_reroute
from service.domain.pipeline.postprocess import run_post_response_hooks
from service.domain.pipeline.processor_flow import build_user_context
from service.domain.run_context import RunExecutionContext, require_execution
from service.events import AgentEvent, EventType
from service.settings import config

logger = logging.getLogger(__name__)


def _step_failed(event) -> bool:
    """Шаг упал. 🔴 Признак есть ТОЛЬКО в событиях шагов, и снять его можно лишь по ходу:
    наблюдатель повторов не вправе копить упавшие цепочки — закрепив такую, платформа
    сделала бы повторение ошибки ДЕТЕРМИНИРОВАННЫМ."""
    return bool((getattr(event, "metadata", None) or {}).get("failed"))


def _workflow_observation_event(steps: tuple[str, ...], user_input: str) -> AgentEvent:
    """Publish one private, normalized observation for backend-owned catalog learning.

    The event is intercepted by backend before websocket publication.  The exact prompt
    is allowed only on this internal hop, then PostgreSQL retains it for 90 days; neither
    the trace nor the Qdrant point payload receives it.
    """
    from service.domain.workflows.observation import Chain
    from service.domain.workflows.proposal import proposal

    execution = require_execution()
    specs = execution.capabilities.static.agents
    candidate = proposal(
        Chain(steps=steps),
        labels={name: spec.label_ru for name, spec in specs.items()},
        costs={name: spec.cost_class for name, spec in specs.items()},
    )
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name="router",
        data="",
        metadata={
            "kind": "workflow_observed",
            "workflow_observed": {
                "steps": list(steps),
                "cost_class": candidate["cost_class"],
                "request_text": str(user_input or ""),
            },
        },
    )


async def _observe_chain(thread_id, decision, route: str | None, failed: bool, user_text: str = ""):
    """Publish a private observation; backend, not a user pin, owns catalog lifecycle."""
    try:
        from service.domain.capabilities import get_workflow

        steps = tuple(
            str(getattr(task, "category", "general")) for task in (decision.subtasks or [])
        )
        # Built-in workflows have their own versioned source. Failed and one-step routes
        # cannot create a catalog entry; failures of an actual catalog execution are
        # reported through `workflow_execution`, where backend updates its quality score.
        if not steps or failed or get_workflow(route or ""):
            return
        return _workflow_observation_event(steps, user_text)
    except Exception:  # noqa: BLE001 — наблюдение не повод ронять отработавший ход
        logger.debug("workflow observation unavailable", extra={"failure_code": "unavailable"})
    return None


def _build_meta_usage_event(execution: RunExecutionContext, cursor: int) -> AgentEvent | None:
    """Событие тарификации СЛУЖЕБНЫХ вызовов (декомпозиция, сложность, план, сжатие).

    Тарифицируются РАЗОМ (аудит P0.3): раньше их usage выбрасывался, а модель бралась
    произвольная — системный недобилл. `None` — вызовов не было (решено эвристикой) или
    они бесплатны.

    ⚠️ `kind` обязателен: по нему потребитель отличает служебный вызов от ответа и не
    показывает ложную «замену модели» (см. `SERVICE_USAGE_KINDS` в `contracts.py`).
    """
    meta_usage = execution.usage.project_kind_since(cursor, "meta_usage")
    if not meta_usage["calls"]:
        return None
    token_usage = {
        "prompt": meta_usage.get("prompt", 0),
        "completion": meta_usage.get("completion", 0),
        "total": meta_usage.get("total", 0),
        "model": meta_usage.get("model"),
    }
    for key in ("provider", "calls", "estimated"):
        if meta_usage.get(key):
            token_usage[key] = meta_usage[key]
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name="planner",
        data="",
        metadata={
            "token_usage": token_usage,
            "kind": "meta_usage",
        },
    )


class AgentProcessor(ProcessorStepsMixin):
    """Main entry point for agent system.

    Provides unified async streaming interface that yields AgentEvent objects.
    """

    def __init__(self, model_settings: dict = None):
        self.orchestrator = Orchestrator(model_settings)
        # Выбранная модель нужна, чтобы считать бюджет контекста от её РЕАЛЬНОГО окна
        # (см. pipeline.context_budget). Раньше она сюда доходила, но игнорировалась,
        # и бюджет был константой 6000 независимо от того, 4k окно у модели или 1M.
        self.model_id = (model_settings or {}).get("model") or None

    async def _auto_knowledge(self, user_id, user_input: str) -> str:
        """База знаний для моделей, которые НЕ умеют function-calling.

        Инструмент `search_knowledge_graph` модель зовёт сама — но только если провайдер
        поддерживает tools. Поддерживают 263 модели из 462: за бортом остаются GigaChat
        и вообще все российские провайдеры. Отрезать их из пикера — значит выбросить
        мультипровайдер, ради которого всё и делалось.

        Поэтому деградация, а не запрет: модель умеет tools → зовёт сама, точно и по
        необходимости; не умеет → ищем сами по её вопросу и кладём найденное в контекст
        отдельной секцией. Менее избирательно, но фича работает ВЕЗДЕ.
        """
        if not user_id or not str(user_input or "").strip():
            return ""
        from service.shared.model_catalog import model_supports_tools

        try:
            if await model_supports_tools(self.model_id or ""):
                return ""  # модель позовёт инструмент сама — дублировать незачем
        except Exception:
            logger.debug("tool capability unavailable", extra={"failure_code": "internal"})
            return ""

        from service.domain.tools import vector_store
        from service.domain.tools.graphify_client import (
            GraphifyClient,
            user_graph_id,
        )

        graph_id = user_graph_id(str(user_id))
        if not graph_id:
            return ""
        try:
            passages, relations = await asyncio.gather(
                vector_store.search(user_id=str(user_id), query=user_input),
                GraphifyClient().query(user_input, graph_id=graph_id),
            )
        except Exception:
            logger.debug("knowledge lookup unavailable", extra={"failure_code": "unavailable"})
            return ""

        parts: list[str] = []
        if passages:
            parts.append(
                "\n\n".join(
                    f"[{hit['filename']}]\n{hit['text']}" for hit in passages if hit.get("text")
                )
            )
        if relations:
            parts.append(f"Связи:\n{relations}")
        return "\n\n".join(p for p in parts if p)

    def _run_single_route(self, decision, user_input: str, context):
        """Одиночный маршрут с однократным ре-роутом на general при сбое.

        Вынесено из `process_message_stream`: та и без того у потолка длины, а этот кусок
        меняется по своей причине — правилам ре-роутинга. Передаём СЫРОЙ вопрос;
        контекст и история едут через `context`.
        """
        return run_with_reroute(
            orchestrator=self.orchestrator,
            agent_name=decision.agent_name,
            user_input=user_input,
            context=context,
            reroute_enabled=_agent_flag(
                "reroute_on_failure_enabled", config.agents.reroute_on_failure_enabled
            ),
        )

    async def process_message_stream(
        self,
        user_input: str,
        thread_id: str,
        user_id: int | None = None,
        session: Any | None = None,
        *,
        route_override: str | None = None,
        resolved_category: str | None = None,
        input_type: str | None = None,
        web_search: bool = False,
        deep_research: bool = False,
        file_context: str | None = None,
        attachments: list | None = None,
        memory_enabled: bool = True,
        multi_intent: bool | None = None,
        planning: bool | None = None,
        memory_parts: tuple[str, str] | None = None,
        history_messages: list[dict] | None = None,
        compact_summary: str | None = None,
        tabular_files: list[dict] | None = None,
        reference_image_url: str | None = None,
        repo_graph_ids: list[str] | None = None,
        has_non_tabular_attachment: bool = False,
        workspace_ref: dict | None = None,
        video_tool_enabled: bool = False,
        execution: RunExecutionContext | None = None,
    ) -> AsyncGenerator[AgentEvent]:
        """Process user message and yield events.

        ``memory_parts`` — уже собранная бэкендом память ``(facts, recall)`` (вынос
        agents в сайдкар, Фаза 0b: данные приходят в запросе, пайплайн не лезет в
        MemoryService сам). Если ``None`` — пайплайн грузит память сам (fallback для
        тестов/прямых вызовов; поведение как раньше).
        Готовые history/summary предпочитаются локальному compatibility fallback:
        сайдкар не имеет доступа к PostgreSQL или Redis backend-а.
        """
        stream = EventSequencer()
        execution = require_execution(execution)

        try:
            context = build_user_context(
                user_id=user_id,
                session=session,
                thread_id=thread_id,
                tabular_files=tabular_files,
                reference_image_url=reference_image_url,
                repo_graph_ids=repo_graph_ids,
                has_non_tabular_attachment=has_non_tabular_attachment,
                workspace_ref=workspace_ref,
                video_tool_enabled=video_tool_enabled,
            )
            # Служебные мета-вызовы (декомпозиция/сложность/план/сжатие) тратят
            # реальные провайдерские токены. Раньше их usage выбрасывался, а модель
            # бралась произвольная (не выбранная юзером) → системный недобилл (P0.3).
            # Копим usage сюда и биллим разом ниже.
            meta_usage_cursor = execution.usage.cursor()

            decision, route_events = await self._resolve_route_and_plan(
                user_input=user_input,
                thread_id=thread_id,
                route_override=route_override,
                resolved_category=resolved_category,
                input_type=input_type,
                web_search=web_search,
                deep_research=deep_research,
                multi_intent=multi_intent,
                planning=planning,
                file_context=file_context,
                attachments=attachments,
                execution=execution,
                # Сигналы для авто-оркестратора: он решает по КОНТЕКСТУ, а прежний
                # роутер видел только текст сообщения.
                context=context,
                history_messages=history_messages,
                compact_summary=compact_summary,
            )
            if decision.context_updates:
                context = context.model_copy(update=decision.context_updates)
            for event in route_events:
                yield stream.attach(event)

            context, context_events = await self._build_context(
                context=context,
                decision=decision,
                user_id=user_id,
                thread_id=thread_id,
                user_input=user_input,
                session=session,
                memory_parts=memory_parts,
                memory_enabled=memory_enabled,
                history_messages=history_messages,
                compact_summary=compact_summary,
                execution=execution,
            )
            for event in context_events:
                yield stream.attach(event)

            # ⚠️ ПОСЛЕ сборки контекста: сжатие досыпает в `meta_usage` свои токены, и
            # раньше словарь был уже сериализован — до 13 вызовов на секцию не биллились.
            meta_event = _build_meta_usage_event(execution, meta_usage_cursor)
            if meta_event is not None:
                yield stream.attach(meta_event)

            if decision.subtasks:
                # Мульти-интент: исполняем шаги и стримим только финальный синтез.
                chain_failed = False  # см. `_observe_chain`: упавшее не наблюдаем
                async for event in execute_steps(
                    orchestrator=self.orchestrator,
                    subtasks=decision.subtasks,
                    context=context,
                    user_input=user_input,
                    # ⚠️ ЧЕРЕЗ OVERLAY, а не из конфига напрямую: соседние флаги в этом же
                    # файле читаются через `_agent_flag`, а этот — нет, и тумблер «потолок
                    # синтеза» в админке не действовал. Сам потолок до недавнего времени
                    # не действовал вообще (не читался в `execute_steps`); чинить его и
                    # оставить неуправляемым из панели значило бы починить наполовину.
                    synthesis_max_tokens=_agent_flag(
                        "subtask_synthesis_max_tokens",
                        config.agents.subtask_synthesis_max_tokens,
                    ),
                ):
                    chain_failed = chain_failed or _step_failed(event)
                    yield stream.attach(event)
                if decision.catalog_workflow is not None:
                    from service.domain.workflows.catalog import execution_event

                    yield stream.attach(
                        execution_event(decision.catalog_workflow, failed=chain_failed)
                    )
                elif offer := await _observe_chain(
                    thread_id, decision, resolved_category, chain_failed, user_input
                ):
                    yield stream.attach(offer)
            else:
                async for event in self._run_single_route(decision, user_input, context):
                    yield stream.attach(event)

            run_post_response_hooks(
                user_id=user_id,
                thread_id=thread_id,
                user_input=user_input,
                logger=logger,
            )

        except Exception as exc:
            yield stream.attach(
                build_processing_error_event(exc, thread_id=thread_id, logger=logger)
            )
