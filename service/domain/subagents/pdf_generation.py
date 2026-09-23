"""Expensive confirmation-gated PDF generator built on Document Forge."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import suppress
from typing import Any

from service.domain.capabilities.agent_spec import COST_EXPENSIVE, AgentSpec
from service.domain.client import list_qualified_models
from service.domain.documents import (
    CitationRegistry,
    DocumentRunOutcome,
    DocumentStage,
    build_document_evidence_bundle,
    document_status_event,
    resolve_document_intent,
)
from service.domain.run_context import require_execution
from service.domain.subagents.base import BaseSubAgent
from service.domain.subagents.pdf_generation_runtime import (
    DocumentGenerationRun,
    authoring_model_meta,
    bind_evidence_policy,
    can_retry_visual_failure,
    create_document_project,
    public_failure,
    publication_artifacts,
    request_digest,
    resumable_document_project,
)
from service.domain.subagents.research import ResearchArtifact
from service.domain.subagents.utils import pick_answer_model
from service.domain.tools.workspace_client import WorkspaceUnavailable
from service.domain.usage_tracking import build_token_usage_meta
from service.events import AgentEvent
from service.schemas.agents import UserContext

logger = logging.getLogger(__name__)

_MODEL_FAILURE_CODES = frozenset(
    {
        "auth",
        "no_compatible_model",
        "payload",
        "provider_protocol",
        "quota",
        "rate_limit",
        "remote",
        "timeout",
        "tls",
        "tls_config",
        "tool_choice",
        "tool_schema",
        "transport",
    }
)

# Compatibility names used by focused tests and older private callers.
_GenerationRun = DocumentGenerationRun
_authoring_model_meta = authoring_model_meta
_bind_evidence_policy = bind_evidence_policy
_can_retry_visual_failure = can_retry_visual_failure
_create_document_project = create_document_project
_public_failure = public_failure
_publication_artifacts = publication_artifacts
_request_digest = request_digest
_resumable_document_project = resumable_document_project


class PDFGenerationAgent(BaseSubAgent):
    # A failed artifact pipeline must never be replaced by a prose answer from
    # general: that path can claim a filename without a verified PDF build.
    allow_failure_reroute = False

    @staticmethod
    def _is_model_failure(exc: BaseException) -> bool:
        return str(getattr(exc, "reason_code", "") or "") in _MODEL_FAILURE_CODES

    def __init__(self, model_settings: dict):
        super().__init__(
            name="pdf_gen",
            instructions="Создаёт проверяемые PDF-документы через изолированный LaTeX runtime.",
            model_settings=model_settings,
        )

    async def _failure_events(
        self,
        message: str,
        *,
        stage: DocumentStage,
        failure_code: str,
        outcome: DocumentRunOutcome = DocumentRunOutcome.FAILED,
        retryable: bool = False,
        usage_meta: dict | None = None,
        model_meta: dict[str, str | None] | None = None,
        project_saved: bool = False,
    ) -> AsyncGenerator[AgentEvent]:
        status = document_status_event(
            self.name,
            stage,
            "failed" if outcome is DocumentRunOutcome.FAILED else outcome.value,
            outcome=outcome,
            failure_code=failure_code,
            retryable=retryable,
        )
        yield status
        async for event in self.stream_text_chunks(message):
            yield event
        yield self.complete_event(
            "PDF не создан" if outcome is DocumentRunOutcome.FAILED else "Черновик PDF сохранён",
            {
                **(usage_meta or {}),
                **(model_meta or {}),
                **({"document_project_saved": True} if project_saved else {}),
                **status.metadata,
            },
        )

    @staticmethod
    def _failure_message(status: dict[str, Any] | None) -> str:
        code = str((status or {}).get("failure_code") or "")
        return {
            "draft_protocol": (
                "Не удалось подготовить структуру документа. Проект сохранён в Работе; "
                "повтор можно продолжить с сохранённого черновика."
            ),
            "draft_invalid": (
                "Не удалось подготовить корректную структуру документа. Проект сохранён "
                "в Работе и не был ошибочно объявлен готовым PDF."
            ),
            "evidence_incomplete": (
                "Черновик PDF сохранён и проверен в Работе, но для финальной статьи "
                "недостаточно библиографических источников. Добавьте источники или отдельно "
                "подтвердите исследование."
            ),
            "unresolved_requirements": (
                "Черновик юридического документа сохранён, но финальная публикация "
                "заблокирована до заполнения обязательных реквизитов."
            ),
            "authoring_unsupported": (
                "Черновик сохранён, но запрошенная структура пока не поддерживается "
                "автоматическим PDF-генератором."
            ),
            "compile_failed": "LaTeX-сборка началась, но завершилась ошибкой компиляции.",
            "deterministic_audit_failed": (
                "PDF собран, но не прошёл обязательную техническую проверку."
            ),
            "visual_audit_failed": "PDF не прошёл обязательную визуальную проверку.",
            "source_conflict": (
                "Исходники изменились во время сборки. Новые правки не перезаписаны."
            ),
            "selected_model_unavailable": (
                "Выбранная модель сейчас недоступна для подготовки документа. "
                "Другая модель не была подставлена."
            ),
            "workspace_unavailable": (
                "Рабочее место временно недоступно. Если проект уже создан, "
                "его исходники сохранены."
            ),
            "cancelled": "Подготовка PDF отменена. Уже сохранённый проект остался в Работе.",
        }.get(
            code,
            "Не удалось завершить подготовку PDF. Если проект был создан, он сохранён в Работе.",
        )

    @staticmethod
    def _failure_stage(status: dict[str, Any] | None) -> DocumentStage:
        stage = str((status or {}).get("stage") or "")
        return {
            "intent": DocumentStage.INTENT,
            "evidence": DocumentStage.EVIDENCE,
            "outline": DocumentStage.OUTLINE,
            "section_authoring": DocumentStage.SECTION_AUTHORING,
            "source_publish": DocumentStage.SOURCE_PUBLISH,
            "compile": DocumentStage.COMPILE,
            "deterministic_audit": DocumentStage.DETERMINISTIC_AUDIT,
            "visual_audit": DocumentStage.VISUAL_AUDIT,
            "delivery": DocumentStage.DELIVERY,
        }.get(stage, DocumentStage.SECTION_AUTHORING)

    async def _emit_final_status(
        self,
        final_status: dict[str, Any] | None,
        *,
        usage_meta: dict,
        model_meta: dict[str, str | None],
    ) -> AsyncGenerator[AgentEvent]:
        state = str((final_status or {}).get("state") or "")
        if state == "draft_ready":
            code = str((final_status or {}).get("failure_code") or "evidence_incomplete")
            async for event in self._failure_events(
                self._failure_message(final_status),
                stage=DocumentStage.EVIDENCE,
                failure_code=code,
                outcome=DocumentRunOutcome.DRAFT_READY,
                usage_meta=usage_meta,
                model_meta=model_meta,
                project_saved=True,
            ):
                yield event
            return
        if state == "visual_pending":
            artifacts = publication_artifacts(final_status or {}, initial_status="pending_audit")
            async for event in self.stream_text_chunks(
                (
                    "PDF собран и прошёл технические проверки. Визуальная проверка временно "
                    "отложена; после неё файл автоматически появится в Библиотеке."
                ),
                metadata={
                    "document_artifacts": artifacts,
                    "document_outcome": DocumentRunOutcome.DEFERRED.value,
                    "document_failure_code": "visual_pending",
                    **model_meta,
                },
            ):
                yield event
            yield document_status_event(
                self.name,
                DocumentStage.VISUAL_AUDIT,
                "pending",
                outcome=DocumentRunOutcome.DEFERRED,
                failure_code="visual_pending",
                retryable=True,
            )
            yield self.complete_event(
                "PDF ожидает визуальной проверки",
                {
                    **usage_meta,
                    "document_outcome": DocumentRunOutcome.DEFERRED.value,
                    "execution_status": "deferred",
                    **model_meta,
                },
            )
            return
        if state != "ready":
            code, stage, retryable = public_failure(final_status)
            async for event in self._failure_events(
                self._failure_message({**(final_status or {}), "failure_code": code}),
                stage=stage,
                failure_code=code,
                retryable=retryable,
                usage_meta=usage_meta,
                model_meta=model_meta,
                project_saved=bool((final_status or {}).get("project_saved")),
            ):
                yield event
            return
        artifacts = publication_artifacts(final_status or {}, initial_status="pending_delivery")
        async for event in self.stream_text_chunks(
            (
                "PDF собран и прошёл техническую проверку. Финальные файлы переданы "
                "для сохранения в Библиотеку."
            ),
            metadata={
                "document_artifacts": artifacts,
                "document_outcome": DocumentRunOutcome.DEFERRED.value,
                "document_failure_code": "delivery_deferred",
                **model_meta,
            },
        ):
            yield event
        yield document_status_event(
            self.name,
            DocumentStage.DELIVERY,
            "queued",
            outcome=DocumentRunOutcome.DEFERRED,
            failure_code="delivery_deferred",
            retryable=True,
        )
        yield self.complete_event(
            "PDF передан для сохранения",
            {
                **usage_meta,
                "document_outcome": DocumentRunOutcome.DEFERRED.value,
                "execution_status": "deferred",
                **model_meta,
            },
        )

    async def _run_document(
        self,
        user_input: str,
        *,
        ref: dict,
        brief: Any,
        evidence: Any,
        citations: CitationRegistry | None,
        model: str,
        model_meta: dict[str, str | None],
        execution: Any,
        usage_cursor: int,
    ) -> AsyncGenerator[AgentEvent]:
        project_path = ""
        generation: DocumentGenerationRun | None = None
        try:
            source_request_digest = request_digest(user_input)
            resumable = (
                await resumable_document_project(
                    ref,
                    source_request_digest=source_request_digest,
                    evidence=evidence,
                    citations=citations,
                )
                if brief.literal_text is None
                else None
            )
            if resumable is None:
                project_path, scaffold_source = await create_document_project(ref, brief)
                checkpoint = None
            else:
                project_path, scaffold_source, checkpoint = resumable
            stage_events: asyncio.Queue[AgentEvent] = asyncio.Queue()

            async def observe_stage(stage: DocumentStage, status: str) -> None:
                await stage_events.put(document_status_event(self.name, stage, status))

            generation = DocumentGenerationRun(
                ref=ref,
                brief=brief,
                model=model,
                project_path=project_path,
                scaffold_source=scaffold_source,
                citations=citations,
                evidence=evidence,
                source_request_digest=source_request_digest,
                resume=checkpoint,
                stage_observer=observe_stage,
            )
            generation_task = asyncio.create_task(generation.execute(execution=execution))
            try:
                while not generation_task.done() or not stage_events.empty():
                    try:
                        yield await asyncio.wait_for(stage_events.get(), timeout=0.2)
                    except TimeoutError:
                        continue
                final_status = await generation_task
            finally:
                if not generation_task.done():
                    generation_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await generation_task
            usage_meta = build_token_usage_meta(execution.usage.project_since(usage_cursor)) or {}
            async for event in self._emit_final_status(
                final_status,
                usage_meta=usage_meta,
                model_meta=model_meta,
            ):
                yield event
        except WorkspaceUnavailable as exc:
            code = str(getattr(exc, "reason_code", "") or "")
            failure_code = "source_conflict" if code == "conflict" else "workspace_unavailable"
            logger.warning("document generation failed code=%s", failure_code)
            async for event in self._failure_events(
                self._failure_message({"failure_code": failure_code}),
                stage=(
                    DocumentStage.COMPILE
                    if generation is not None and generation.compile_started
                    else DocumentStage.SOURCE_PUBLISH
                ),
                failure_code=failure_code,
                retryable=True,
                usage_meta=build_token_usage_meta(execution.usage.project_since(usage_cursor)),
                model_meta=model_meta,
                project_saved=bool(project_path),
            ):
                yield event
        except Exception as exc:
            failure_code = (
                "selected_model_unavailable" if self._is_model_failure(exc) else "internal"
            )
            logger.warning("document generation failed code=%s", failure_code)
            async for event in self._failure_events(
                self._failure_message({"failure_code": failure_code}),
                stage=(
                    DocumentStage.COMPILE
                    if generation is not None and generation.compile_started
                    else DocumentStage.SECTION_AUTHORING
                ),
                failure_code=failure_code,
                usage_meta=build_token_usage_meta(execution.usage.project_since(usage_cursor)),
                model_meta=model_meta,
                project_saved=bool(project_path),
            ):
                yield event

    async def process(self, user_input: str, context: UserContext) -> AsyncGenerator[AgentEvent]:
        yield self.start_event("Готовлю PDF-документ")
        execution = require_execution()
        usage_cursor = execution.usage.cursor()
        requested_model = self.preferred_model()
        model_meta = authoring_model_meta(requested_model, None)
        ref = getattr(context, "workspace_ref", None)
        if not isinstance(ref, dict):
            async for event in self._failure_events(
                "Для создания PDF требуется рабочее место этого чата.",
                stage=DocumentStage.SOURCE_PUBLISH,
                failure_code="workspace_unavailable",
                retryable=True,
                model_meta=model_meta,
            ):
                yield event
            return
        model = pick_answer_model(await list_qualified_models(), requested_model)
        if not model:
            async for event in self._failure_events(
                self._failure_message({"failure_code": "selected_model_unavailable"}),
                stage=DocumentStage.INTENT,
                failure_code="selected_model_unavailable",
                model_meta=model_meta,
            ):
                yield event
            return
        model_meta = authoring_model_meta(requested_model or model, model)
        yield document_status_event(self.name, DocumentStage.INTENT, "running")
        try:
            brief = await resolve_document_intent(user_input, model, execution=execution)
        except Exception as exc:
            failure_code = (
                "selected_model_unavailable" if self._is_model_failure(exc) else "internal"
            )
            logger.warning("document intent failed code=%s", failure_code)
            async for event in self._failure_events(
                self._failure_message({"failure_code": failure_code}),
                stage=DocumentStage.INTENT,
                failure_code=failure_code,
                usage_meta=build_token_usage_meta(execution.usage.project_since(usage_cursor)),
                model_meta=model_meta,
            ):
                yield event
            return
        research = execution.artifacts.get("research.latest", ResearchArtifact)
        evidence = build_document_evidence_bundle(context.current_attachments, research)
        citations = CitationRegistry(evidence.bibliography) if evidence.has_bibliography else None
        brief = bind_evidence_policy(brief, citations)
        yield document_status_event(
            self.name,
            DocumentStage.EVIDENCE,
            "ready" if evidence.has_materials else "empty",
            facts=evidence.summary(),
        )
        async for event in self._run_document(
            user_input,
            ref=ref,
            brief=brief,
            evidence=evidence,
            citations=citations,
            model=model,
            model_meta=model_meta,
            execution=execution,
            usage_cursor=usage_cursor,
        ):
            yield event


SPEC = AgentSpec(
    name="pdf_gen",
    label_ru="PDF-документ",
    build=PDFGenerationAgent,
    billing_name="pdf_gen",
    cost_class=COST_EXPENSIVE,
    confirm_by_default=True,
    prompt_hint=(
        "просят создать готовый PDF, статью, юридический документ, отчёт или "
        "PDF-презентацию; редактирование существующего .tex файла может выполнить general "
        "с tex tools"
    ),
)
