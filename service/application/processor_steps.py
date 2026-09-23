"""Подготовительные шаги конвейера: КТО отвечает и ЧТО он видит.

Примесь, а не свободные функции: шагам нужны ``self.model_id``, ``self.orchestrator`` и
``self._auto_knowledge``.

⚠️ Шаги СОБИРАЮТ события списком, а не йелдят: так каждый остаётся обычной функцией,
которую можно позвать из теста без драйвера генератора.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from service.application.processor_context import (
    _files_for_prompt,
    attachment_text_reaches_prompt,
    build_context_step,
)
from service.application.repo_map import is_repo_map
from service.domain.pipeline.auto_mode import apply_plan, resolve_auto_plan
from service.domain.pipeline.context_compressor import make_compressor
from service.domain.pipeline.decomposition import decompose_intents
from service.domain.pipeline.multimodal import (
    build_multimodal_route_events,
    fanout_context,
    normalize_attachments,
    should_fan_out,
)
from service.domain.pipeline.planning import plan_blockers, resolve_plan
from service.domain.pipeline.processor_flow import resolve_agent_route
from service.domain.pipeline.workflow_catalog_selection import resolve_workflow_route
from service.domain.run_context import RunExecutionContext, require_execution
from service.events import AgentEvent, EventType
from service.settings import config
from service.shared.agent_settings import runtime_settings

logger = logging.getLogger(__name__)


def _agent_flag(name, default):
    """Runtime-настройка агентов из админ-overlay (fail-safe → дефолт из config)."""
    return runtime_settings.get_agents(name, default)


@dataclass(frozen=True)
class RouteDecision:
    """Кто и как отвечает на этот запрос — итог фазы маршрутизации.

    Именованные поля, а не кортеж из пяти: ``subtasks`` и ``multimodal`` независимы
    (мульти-интент и вложения ортогональны), и путать их местами при распаковке —
    ровно тот класс ошибки, из-за которого декомпозиция когда-то молча отменялась
    любыми двумя вложениями.
    """

    agent_name: str
    subtasks: list | None
    plan_context: str | None
    # Контекст вложений: свой + агрегированный fan-out'ом, если он был.
    file_context: str
    multimodal: bool
    # Не сериализуется в trace: это уже отобранный внутренний каталогом сценарий.
    catalog_workflow: Any | None = None
    context_updates: dict[str, Any] | None = None


def _orchestrator_flags() -> dict:
    """Настройки оркестратора из админ-снимка.

    Отдельно от вызова: это чтение конфигурации, а не решение о маршруте, и в теле шага оно
    мешало видеть сам конвейер.
    """
    return {
        "enabled": _agent_flag(
            "auto_orchestrator_enabled", config.agents.auto_orchestrator_enabled
        ),
        "confirm_modes": _agent_flag("auto_confirm_modes", config.agents.auto_confirm_modes),
    }


def _prepare_modality(
    attachments: list | None,
    *,
    route_override: str | None,
) -> tuple[list[dict], bool]:
    """Нормализовать вложения и зафиксировать их только в run-scoped context.

    Subagents читают структурированные вложения из контекста текущего запуска. Этот
    helper держит запись рядом с нормализацией и не даёт маршрутизатору случайно
    использовать исходные, неоднородные payloads.
    """
    normalized = normalize_attachments(attachments)
    return normalized, should_fan_out(normalized, route_override=route_override)


def _multi_intent_route_event(step_count: int) -> AgentEvent:
    return AgentEvent(
        type=EventType.ROUTING_COMPLETE,
        agent_name="general",
        data=f"Мульти-интент: {step_count} шага",
        metadata={"multi_intent": True, "steps": step_count},
    )


class ProcessorStepsMixin:
    """Шаги подготовки ответа. Требования к хозяину — в докстринге модуля."""

    async def _resolve_route_and_plan(
        self,
        *,
        user_input: str,
        thread_id: str,
        route_override: str | None,
        resolved_category: str | None,
        input_type: str | None,
        web_search: bool,
        deep_research: bool,
        multi_intent: bool | None,
        planning: bool | None,
        file_context: str | None,
        attachments: list | None,
        execution: RunExecutionContext | None = None,
        context: Any = None,
        history_messages: list[dict] | None = None,
        compact_summary: str | None = None,
        **compatibility,
    ) -> tuple[RouteDecision, list[AgentEvent]]:
        """Решить, кто и как отвечает: fan-out, декомпозиция, маршрут и план."""
        compatibility.pop("meta_usage", None)
        if compatibility:
            unexpected = next(iter(compatibility))
            raise TypeError(f"unexpected compatibility keyword: {unexpected}")
        execution = require_execution(execution)
        events: list[AgentEvent] = []
        subtasks = None
        catalog_workflow = None
        plan_context: str | None = None
        modality_attachments, multimodal = _prepare_modality(
            attachments,
            route_override=route_override,
        )

        # Один контекстный вызов вместо роутера на одну метку. При форсе и любом сбое
        # возвращает пустой план — тогда всё ниже работает как раньше.
        auto = await resolve_auto_plan(
            user_input=user_input,
            context=context,
            history_messages=history_messages,
            compact_summary=compact_summary,
            route_override=route_override,
            input_type=input_type,
            web_search=web_search,
            deep_research=deep_research,
            multimodal=multimodal,
            resolved_category=resolved_category,
            attachments=modality_attachments,
            multi_intent=multi_intent,
            planning=planning,
            model=self.model_id,
            execution=execution,
            # 🔴 ФАКТЫ, а не догадки. Карта репозитория содержимым НЕ является: см. `is_repo_map`.
            attachment_text_in_prompt=attachment_text_reaches_prompt(context, file_context),
            attachment_text_in_prompt_is_a_map=is_repo_map(file_context),
            **_orchestrator_flags(),
        )
        events.extend(auto.events)
        multi_intent, planning, resolved_category = apply_plan(
            auto,
            context=context,
            multi_intent=multi_intent,
            planning=planning,
            resolved_category=resolved_category,
            execution=execution,
        )

        # Мульти-интент и вложения — ОРТОГОНАЛЬНЫ. Раньше декомпозиция жила в `else`
        # к `if multimodal`, поэтому любые два вложения молча отменяли её: человек
        # жал тумблер, прикладывал файлы — и получал обычный однопроходный ответ, не
        # понимая, почему кнопка «не работает». Fan-out готовит КОНТЕКСТ, декомпозиция
        # делит ЗАДАЧУ; ни одно не отменяет другое.
        merged_file_context = file_context
        if multimodal:
            merged_file_context, fanout_events = await fanout_context(
                modality_attachments, user_input, file_context, execution=execution
            )
            events.extend(fanout_events)

        workflow_route = await resolve_workflow_route(
            user_input=user_input,
            route_override=route_override,
            resolved_category=resolved_category,
            multi_intent=multi_intent,
            web_search=web_search,
            deep_research=deep_research,
            input_type=input_type,
            force_decompose=auto.force_decompose,
            max_subtasks=_agent_flag("max_subtasks", config.agents.max_subtasks),
            model=self.model_id,
            execution=execution,
            decompose=decompose_intents,
        )
        subtasks = workflow_route.subtasks
        catalog_workflow = workflow_route.candidate
        route_override = workflow_route.route_override
        resolved_category = workflow_route.resolved_category
        events.extend(workflow_route.events)
        if subtasks:
            agent_name = "general"
            events.append(_multi_intent_route_event(len(subtasks)))
        elif multimodal:
            # Финальный агент мультимодальной ветки — general (агрегация).
            agent_name = "general"
            events.extend(build_multimodal_route_events(len(modality_attachments)))
        else:
            agent_name, routing_start, routing_complete = await resolve_agent_route(
                orchestrator=self.orchestrator,
                user_input=user_input,
                thread_id=thread_id,
                route_override=route_override,
                input_type=input_type,
                web_search=web_search,
                deep_research=deep_research,
                execution=execution,
                resolved_category=resolved_category,
            )
            events.extend((routing_start, routing_complete))

        plan_context, plan_events = await resolve_plan(
            user_input,
            planning=planning,
            model=self.model_id,
            execution=execution,
            blockers=plan_blockers(
                subtasks=subtasks,
                multimodal=multimodal,
                agent_name=agent_name,
                route_override=route_override,
                web_search=web_search,
                deep_research=deep_research,
            ),
        )
        events.extend(plan_events)

        return (
            RouteDecision(
                agent_name=agent_name,
                subtasks=subtasks,
                plan_context=plan_context,
                file_context=merged_file_context or "",
                multimodal=multimodal,
                catalog_workflow=catalog_workflow,
                context_updates={"current_attachments": modality_attachments},
            ),
            events,
        )

    async def _build_context(
        self,
        *,
        context: Any,
        decision: RouteDecision,
        user_id: int | None,
        thread_id: str,
        user_input: str,
        session: Any | None,
        memory_parts: tuple[str, str] | None,
        memory_enabled: bool,
        history_messages: list[dict] | None,
        compact_summary: str | None,
        execution: RunExecutionContext,
    ) -> tuple[Any, list[AgentEvent]]:
        """Собрать контекст под бюджет окна и записать его в ``context``."""
        return await build_context_step(
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
            model_id=self.model_id,
            orchestrator=self.orchestrator,
            auto_knowledge=self._auto_knowledge,
            compressor_factory=make_compressor,
        )


__all__ = ["ProcessorStepsMixin", "RouteDecision", "_files_for_prompt"]
