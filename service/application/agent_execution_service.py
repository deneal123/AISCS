from __future__ import annotations

from typing import Any

from service.application.processor import AgentProcessor
from service.application.reply_assembler import ReplyAssembler
from service.application.use_cases.agent_execution_use_cases import (
    PersistSessionHistoryUseCase,
    PostprocessAgentReplyUseCase,
    PrepareExecutionContextUseCase,
    RouteModelUseCase,
    RunAgentUseCase,
)
from service.domain.persona import context as persona_context
from service.domain.persona import registry as persona_registry
from service.domain.run_context import PrivateRunResources, use_run_execution
from service.domain.tools import found_sources, unbilled_calls
from service.shared import step_timing


# Базовый класс снят: AgentExecutionPort — DI-шов BACKEND'а (он выбирает между
# in-process и HTTP-движком). Сайдкар — терминальная точка исполнения, выбирать ему
# не из чего, и наследоваться от чужого порта значило бы держать связь ради подписи.
class DefaultAgentExecutionService:
    async def execute(
        self,
        *,
        text: str,
        thread_id: str,
        user_id: str | None,
        session_data: dict | None,
        selected_model: str | None,
        route_override: str | None,
        resolved_category: str | None = None,
        input_type: str | None,
        web_search: bool,
        deep_research: bool,
        file_context: str,
        attachments: list | None = None,
        pseudo_session: Any | None = None,
        on_event: Any | None = None,
        memory_enabled: bool = True,
        ldr_model: str | None = None,
        ldr_strategy: str | None = None,
        multi_intent: bool | None = None,
        memory_parts: tuple[str, str] | None = None,
        history_messages: list[dict] | None = None,
        compact_summary: str | None = None,
        tabular_files: list[dict] | None = None,
        reference_image_url: str | None = None,
        repo_graph_ids: list[str] | None = None,
        has_non_tabular_attachment: bool = False,
        persona_ids: list[str] | None = None,
        persona_switched: bool = False,
        planning: bool | None = None,
        workspace_ref: dict | None = None,
        # Согласие человека на дорогой просмотр ролика — из ЭТОГО сообщения.
        video_tool_enabled: bool = False,
    ) -> dict[str, Any]:
        lens = persona_registry.build_lens(persona_ids, switched=persona_switched)
        private_resources = PrivateRunResources.from_request(
            workspace_ref=workspace_ref,
            tabular_files=tabular_files,
            reference_image_url=reference_image_url,
            repo_graph_ids=repo_graph_ids,
        )
        with (
            use_run_execution(private_resources) as run_execution,
            persona_context.use_persona(lens),
            step_timing.collect() as timings,
            found_sources.collect(),
            # Отказы инструментов копятся здесь же: за неоказанную услугу надбавки нет.
            unbilled_calls.collect(),
        ):
            from service.domain.client.registry import initialize_run_provider_admission

            await initialize_run_provider_admission(run_execution)
            with step_timing.step("route_model"):
                resolved_model, routing_meta = await RouteModelUseCase().execute(
                    text=text,
                    selected_model=selected_model,
                    input_type=input_type,
                    execution=run_execution,
                )
            context = PrepareExecutionContextUseCase().execute(
                routing_meta=routing_meta,
                route_override=route_override,
                resolved_category=resolved_category,
                web_search=web_search,
                deep_research=deep_research,
                session_data=session_data,
                thread_id=thread_id,
                pseudo_session=pseudo_session,
                input_type=input_type,
            )

            processor = AgentProcessor(
                model_settings={
                    "model": resolved_model or "mws-gpt-alpha",
                    "temperature": 0.7,
                    "max_tokens": 1000,
                    # Per-user модель и стратегия LDR (глубокий ресёрч); читаются в
                    # DeepResearchAgent._resolve_ldr_settings. None → overlay/config.
                    "ldr_model": ldr_model,
                    "ldr_strategy": ldr_strategy,
                }
            )
            reply_assembler = ReplyAssembler(run_execution.usage)
            metadata: dict[str, Any] = {}
            if not lens.is_empty:
                # В трейс и в сохранённый итог: иначе «почему ответ такой» невозможно
                # объяснить постфактум, а отброшенный выбор (неизвестный id, потолок,
                # blend_deny) выглядел бы как «личность не работает».
                metadata["persona_ids"] = list(lens.ids)
                reply_assembler.metadata["persona_ids"] = list(lens.ids)
            if routing_meta:
                metadata["model_routing"] = routing_meta
                reply_assembler.metadata["model_routing"] = routing_meta

            with step_timing.step("agent_run"):
                await RunAgentUseCase().execute(
                    processor=processor,
                    reply_assembler=reply_assembler,
                    metadata=metadata,
                    on_event=on_event,
                    user_input=text,
                    thread_id=thread_id,
                    user_id=user_id,
                    session=context["pseudo_session"],
                    route_override=context["route_override"],
                    resolved_category=context["resolved_category"],
                    input_type=input_type,
                    web_search=context["web_search"],
                    deep_research=context["deep_research"],
                    file_context=file_context,
                    attachments=attachments,
                    memory_enabled=memory_enabled,
                    multi_intent=multi_intent,
                    planning=planning,
                    memory_parts=memory_parts,
                    history_messages=history_messages,
                    compact_summary=compact_summary,
                    tabular_files=tabular_files,
                    workspace_ref=workspace_ref,
                    video_tool_enabled=video_tool_enabled,
                    execution=run_execution,
                    reference_image_url=reference_image_url,
                    repo_graph_ids=repo_graph_ids,
                    has_non_tabular_attachment=has_non_tabular_attachment,
                )
            reply_assembler.finalize_usage()
            reply, metadata = PostprocessAgentReplyUseCase().execute(
                reply_assembler=reply_assembler, metadata=metadata
            )
            # Тайминги уезжают тем же каналом, что и отчёт о занятости окна
            # (`metadata.context`), — значит видны в трейсе без новых ручек.
            metadata["timings"] = timings.as_meta()
            # Прочитанные ссылки — тем же каналом. Ключ `sources` уже персистится
            # бэкендом и уже рисуется фронтом: новый вид списка означал бы вторую
            # разметку и вторую причину чинить.
            found = found_sources.collected()
            if found:
                metadata["sources"] = found
            artifacts = await _workspace_artifacts(workspace_ref)
            return PersistSessionHistoryUseCase().execute(
                reply=reply,
                metadata=metadata,
                resolved_model=resolved_model or "mws-gpt-alpha",
                reply_assembler=reply_assembler,
                workspace_artifacts=artifacts,
            )


async def _workspace_artifacts(workspace_ref: dict | None) -> list[dict]:
    """Опись созданного в песочнице — в конце прогона и только если песочница была."""
    if not workspace_ref:
        return []
    from service.domain.tools.workspace_client import list_artifacts

    return await list_artifacts(workspace_ref)
