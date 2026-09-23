"""Context preparation for the message processor.

Routing and context assembly evolve independently.  Keeping this stage outside the
processor mixin makes its inputs explicit and prevents the composition module from
becoming the owner of memory, attachment, compression, and prompt-budget policy.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from service.application.repo_map import annotate_repo_map
from service.domain.pipeline.context_assembler import assemble_context, build_context_summary
from service.domain.pipeline.context_compressor import make_compressor
from service.domain.pipeline.context_enricher import resolve_history, resolve_memory_parts
from service.domain.run_context import RunExecutionContext
from service.events import AgentEvent, EventType
from service.settings import config
from service.shared.agent_settings import runtime_settings

logger = logging.getLogger(__name__)

KnowledgeLookup = Callable[[int | None, str], Awaitable[str]]
CompressorFactory = Callable[..., Any]


def _agent_flag(name: str, default: Any) -> Any:
    return runtime_settings.get_agents(name, default)


def _tabular_notice(context: Any) -> str:
    names = [
        str((item or {}).get("name") or "").strip()
        for item in (getattr(context, "tabular_files", None) or [])
    ]
    names = [name for name in names if name]
    listed = ", ".join(f"«{name}»" for name in names[:10]) if names else "табличные файлы"
    return (
        f"⚠️ К ЭТОМУ ДИАЛОГУ ПРИЛОЖЕНЫ ТАБЛИЧНЫЕ ДАННЫЕ: {listed}. Их содержимое НЕ вложено "
        "в промпт текстом — читай их инструментом `analyze_data` (первый вызов БЕЗ sql "
        "вернёт схему и первые строки, дальше пиши SQL). НЕ проси пользователя приложить "
        "или загрузить файл: он уже загружен и доступен через инструмент.\n\n"
    )


def _tabular_text_is_dropped(context: Any) -> bool:
    return bool(getattr(context, "tabular_files", None)) and not bool(
        getattr(context, "has_non_tabular_attachment", False)
    )


def attachment_text_reaches_prompt(context: Any, file_context: str | None) -> bool:
    """Whether extracted attachment text, rather than a tool pointer, reaches the model."""

    return bool(str(file_context or "").strip()) and not _tabular_text_is_dropped(context)


def _files_for_prompt(context: Any, file_context: str) -> tuple[str, bool]:
    """Project attachment text without duplicating tabular data in every tool round."""

    if _tabular_text_is_dropped(context):
        return _tabular_notice(context), bool(str(file_context or "").strip())
    return annotate_repo_map(file_context), False


def _fixed_prompt_tokens(orchestrator: Any, agent_name: str, context: Any) -> int:
    try:
        agent = orchestrator.get_agent(agent_name)
        measure = getattr(agent, "fixed_prompt_tokens", None)
        return int(measure(context)) if callable(measure) else 0
    except Exception:  # noqa: BLE001
        logger.debug("prompt baseline unavailable", extra={"failure_code": "internal"})
        return 0


async def build_context_step(
    *,
    context: Any,
    decision: Any,
    user_id: int | None,
    thread_id: str,
    user_input: str,
    session: Any | None,
    memory_parts: tuple[str, str] | None,
    memory_enabled: bool,
    history_messages: list[dict] | None,
    compact_summary: str | None,
    execution: RunExecutionContext,
    model_id: str,
    orchestrator: Any,
    auto_knowledge: KnowledgeLookup,
    compressor_factory: CompressorFactory = make_compressor,
) -> tuple[Any, list[AgentEvent]]:
    """Assemble one internally consistent prompt context and its safe status events."""

    events: list[AgentEvent] = []
    facts_context, memory_context = await resolve_memory_parts(
        memory_parts,
        user_id=user_id,
        memory_enabled=memory_enabled,
        query=user_input,
        logger=logger,
    )
    history_items = await resolve_history(
        history_messages,
        session,
        logger,
        compact_summary=compact_summary or "",
        history_limit=_agent_flag(
            "chat_history_messages_limit", config.agents.chat_history_messages_limit
        ),
        summary_keep_recent=_agent_flag("summary_keep_recent", config.agents.summary_keep_recent),
    )
    knowledge_context = (
        "" if decision.file_context.strip() else await auto_knowledge(user_id, user_input)
    )
    if knowledge_context:
        events.append(
            AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name="knowledge",
                data="База знаний: найдено по вашему вопросу (модель без вызова инструментов)",
                metadata={"knowledge_chars": len(knowledge_context)},
            )
        )

    files_for_prompt, skipped_tabular = _files_for_prompt(context, decision.file_context)
    if skipped_tabular:
        events.append(
            AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name="context",
                data="Табличный файл — анализирую через SQL (analyze_data), не текстом",
                metadata={"tabular_inline_skipped": True},
            )
        )

    compressor = compressor_factory(config, execution=execution)
    assembled = await assemble_context(
        model_id=model_id,
        config=config,
        user_input=user_input,
        facts=facts_context,
        memory=memory_context,
        files=files_for_prompt,
        knowledge=knowledge_context,
        plan=decision.plan_context or "",
        summary=compact_summary,
        history=history_items,
        compressor=compressor,
        fixed_tokens=_fixed_prompt_tokens(orchestrator, decision.agent_name, context),
    )
    updated_context = context.model_copy(
        update={
            "history_messages": assembled.history_messages,
            "system_context": assembled.system_context,
        }
    )
    logger.info(
        "Контекст собран: %s/%s токенов (окно %s) — %s",
        assembled.used,
        assembled.budget.usable,
        assembled.budget.window,
        assembled.by_section,
    )
    threshold_pct = int(
        float(_agent_flag("compaction_threshold", config.agents.compaction_threshold)) * 100
    )
    events.append(
        AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name=decision.agent_name,
            data=build_context_summary(assembled),
            metadata={"context": assembled.as_meta(threshold_pct=threshold_pct)},
        )
    )
    return updated_context, events


__all__ = ["_files_for_prompt", "attachment_text_reaches_prompt", "build_context_step"]
