"""Ledger-native semantic authoring with resumable, bounded section rounds."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from service.domain.client import create_chat_completion
from service.domain.documents.authoring.checkpoint import (
    CheckpointWriter,
    DocumentAuthoringCheckpoint,
    allowed_outline_sources,
    restore_authoring_checkpoint,
)
from service.domain.documents.authoring.protocol import (
    INTENT_FUNCTION,
    INTENT_TOOL,
    OUTLINE_FUNCTION,
    OUTLINE_TOOL,
    SECTION_FUNCTION,
    compile_section_tool,
    response_arguments,
)
from service.domain.documents.authoring.repair import repair_semantic_draft
from service.domain.documents.evidence.bundle import DocumentEvidenceBundle
from service.domain.documents.evidence.citations import CitationRegistry
from service.domain.documents.intent import (
    DocumentIntent,
    deterministic_intent,
    literal_shortcut,
    parse_document_intent,
)
from service.domain.documents.semantic.draft import DocumentDraft, DraftBlock
from service.domain.documents.semantic.outline import (
    DocumentOutline,
    DocumentOutlineSection,
    OutlineRejectionReason,
    ensure_required_outline_sections,
    parse_document_outline_result,
    section_role,
)
from service.domain.documents.semantic.section_parser import (
    AuthoringFailureCode,
    AuthoringRejectionReason,
    parse_authored_section,
)
from service.domain.documents.skills.catalog import DOCUMENT_SKILL_CATALOG
from service.domain.execution.context import RunExecutionContext
from service.domain.execution.model import invoke_model_call
from service.domain.usage.ledger import UsageKind

AuthoringFailureStage = Literal["outline", "section_authoring"]
AuthoringStageWriter = Callable[[AuthoringFailureStage], Awaitable[None]]
_SECTION_CONTENT_KINDS: dict[str, frozenset[str]] = {
    "presentation": frozenset({"slide"}),
    "article": frozenset(
        {"paragraph", "list", "table", "figure", "equation", "callout", "citation"}
    ),
    "report": frozenset(
        {"paragraph", "list", "table", "figure", "equation", "callout", "citation"}
    ),
    "legal": frozenset({"paragraph", "list", "table", "callout", "signature"}),
    "generic": frozenset(
        {"paragraph", "list", "table", "figure", "equation", "callout", "signature"}
    ),
}


@dataclass(frozen=True, slots=True)
class DocumentAuthoringResult:
    draft: DocumentDraft | None
    failure_code: AuthoringFailureCode | None = None
    repair_used: bool = False
    accepted_sections: int = 0
    failure_stage: AuthoringFailureStage | None = None
    rejection_reason: AuthoringRejectionReason | OutlineRejectionReason | None = None

    @property
    def accepted(self) -> bool:
        return self.draft is not None and self.failure_code is None


def _owner(execution: RunExecutionContext, model: str) -> str | None:
    return execution.provider_snapshot.owner_for(model) if execution.provider_snapshot else None


async def resolve_document_intent(
    request: str, model: str, *, execution: RunExecutionContext
) -> DocumentIntent:
    literal = literal_shortcut(request)
    if literal is not None:
        return literal
    result = await invoke_model_call(
        create_chat_completion,
        kind=UsageKind.PDF_AUTHORING,
        execution=execution,
        messages=[
            {
                "role": "system",
                "content": (
                    "Определи замысел документа. Зафиксированные ограничения профиля "
                    "нельзя переопределять."
                ),
            },
            {"role": "user", "content": str(request or "")[:24_000]},
        ],
        model=model,
        temperature=0,
        max_tokens=900,
        tools=[INTENT_TOOL],
        tool_choice={"type": "function", "function": {"name": INTENT_FUNCTION}},
        pin_provider=_owner(execution, model),
    )
    parsed = response_arguments(result.response, INTENT_FUNCTION)
    intent = parse_document_intent(parsed or {}, request)
    return intent or deterministic_intent(request)


def _draft_prompt(intent: DocumentIntent, evidence: DocumentEvidenceBundle | None) -> str:
    requirements = "\n".join(f"- {item}" for item in intent.user_requirements)
    source_context = evidence.prompt_context() if evidence is not None else ""
    legal_fields = json.dumps(
        [
            {"name": item.name, "value": item.value, "required": item.required}
            for item in intent.legal_fields
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"Запрос:\n{intent.request}\n\nВид: {intent.kind}; название: {intent.title}; "
        f"аудитория: {intent.audience}; объём: {intent.length_class}; плотность: "
        f"{intent.presentation_density}.\nОбязательные разделы: "
        f"{', '.join(intent.required_sections)}\n"
        f"Требования пользователя:\n{requirements}\nЮридические реквизиты:\n{legal_fields}\n\n"
        "Зарегистрированные источники (идентификаторы материалов обозначают происхождение; "
        f"в блоках цитирования допустимы только числовые идентификаторы):\n{source_context}"
    )


async def _invoke_outline_round(
    intent: DocumentIntent,
    model: str,
    *,
    execution: RunExecutionContext,
    citations: CitationRegistry | None,
    evidence: DocumentEvidenceBundle | None,
    repair: bool,
) -> tuple[DocumentOutline | None, OutlineRejectionReason | None]:
    instruction = DOCUMENT_SKILL_CATALOG.semantic_instruction(intent.profile_id)
    instruction += (
        " Предыдущий ответ нарушил протокол вызова функций. Верни ровно один корректный "
        "вызов функции без текстовых пояснений."
        if repair
        else (
            " Сначала составь краткий план. Точно копируй идентификаторы источников "
            "из предоставленных материалов; не выдумывай факты об источниках."
        )
    )
    result = await invoke_model_call(
        create_chat_completion,
        kind=UsageKind.PDF_AUTHORING,
        execution=execution,
        messages=[
            {"role": "system", "content": instruction},
            {"role": "user", "content": _draft_prompt(intent, evidence)},
        ],
        model=model,
        temperature=0.2,
        max_tokens=2_000,
        tools=[OUTLINE_TOOL],
        tool_choice={"type": "function", "function": {"name": OUTLINE_FUNCTION}},
        pin_provider=_owner(execution, model),
    )
    arguments = response_arguments(result.response, OUTLINE_FUNCTION)
    outline, rejection = parse_document_outline_result(
        arguments,
        allowed_source_ids=allowed_outline_sources(citations, evidence),
    )
    if outline is None:
        return None, rejection
    return ensure_required_outline_sections(outline, intent.required_sections), None


def _section_prompt(
    intent: DocumentIntent,
    outline: DocumentOutline,
    section: DocumentOutlineSection,
    citations: CitationRegistry | None,
    evidence: DocumentEvidenceBundle | None,
) -> str:
    return json.dumps(
        {
            "intent": {
                "kind": intent.kind,
                "locale": intent.locale,
                "title": outline.title,
                "audience": intent.audience,
                "length_class": intent.length_class,
                "citation_policy": intent.citation_policy,
            },
            "section": section.payload(),
            "registered_citation_ids": (sorted(_section_citations(section, citations, evidence))),
            "evidence": (
                evidence.prompt_context(max_chars=18_000, source_ids=section.source_ids or None)
                if evidence is not None
                else ""
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _section_citations(
    section: DocumentOutlineSection,
    citations: CitationRegistry | None,
    evidence: DocumentEvidenceBundle | None,
) -> frozenset[int]:
    if citations is None:
        return frozenset()
    if evidence is None:
        return citations.artifact.source_ids
    visible = evidence.project_context(
        max_chars=18_000, source_ids=section.source_ids or None
    ).citation_ids
    return citations.artifact.source_ids & visible


async def _invoke_section_round(
    intent: DocumentIntent,
    outline: DocumentOutline,
    section: DocumentOutlineSection,
    model: str,
    *,
    execution: RunExecutionContext,
    citations: CitationRegistry | None,
    evidence: DocumentEvidenceBundle | None,
    repair: bool,
) -> tuple[
    tuple[DraftBlock, ...] | None,
    AuthoringFailureCode | None,
    AuthoringRejectionReason | None,
]:
    if (
        evidence is not None
        and not evidence.project_context(
            max_chars=18_000, source_ids=section.source_ids or None
        ).complete
    ):
        return None, "evidence_incomplete", None
    instruction = DOCUMENT_SKILL_CATALOG.semantic_instruction(intent.profile_id)
    offered_citations = _section_citations(section, citations, evidence)
    instruction += (
        " Предыдущий ответ некорректен. Верни ровно один корректный вызов функции "
        "подготовки раздела без текстовых пояснений."
        if repair
        else (
            " Подготовь только один предоставленный раздел. Идентификаторы разделов и блоков "
            "назначает система; верни только блоки с зарегистрированными числовыми "
            "идентификаторами источников."
        )
    )
    result = await invoke_model_call(
        create_chat_completion,
        kind=UsageKind.PDF_AUTHORING,
        execution=execution,
        messages=[
            {"role": "system", "content": instruction},
            {
                "role": "user",
                "content": _section_prompt(intent, outline, section, citations, evidence),
            },
        ],
        model=model,
        temperature=0.2,
        max_tokens=3_500,
        tools=[
            compile_section_tool(
                offered_citations,
                _SECTION_CONTENT_KINDS.get(intent.kind, frozenset({"paragraph"})),
            )
        ],
        tool_choice={"type": "function", "function": {"name": SECTION_FUNCTION}},
        pin_provider=_owner(execution, model),
    )
    return parse_authored_section(
        response_arguments(result.response, SECTION_FUNCTION),
        section,
        citations,
        document_kind=intent.kind,
        allowed_source_ids=offered_citations,
    )


async def _outline_with_single_repair(
    intent: DocumentIntent,
    model: str,
    *,
    execution: RunExecutionContext,
    citations: CitationRegistry | None,
    evidence: DocumentEvidenceBundle | None,
) -> tuple[DocumentOutline | None, bool, OutlineRejectionReason | None]:
    outline, rejection = await _invoke_outline_round(
        intent,
        model,
        execution=execution,
        citations=citations,
        evidence=evidence,
        repair=False,
    )
    if outline is not None:
        return outline, False, None
    outline, rejection = await _invoke_outline_round(
        intent,
        model,
        execution=execution,
        citations=citations,
        evidence=evidence,
        repair=True,
    )
    return outline, True, rejection


async def author_semantic_draft_result(
    intent: DocumentIntent,
    model: str,
    *,
    execution: RunExecutionContext,
    citations: CitationRegistry | None,
    evidence: DocumentEvidenceBundle | None = None,
    checkpoint: CheckpointWriter | None = None,
    resume: DocumentAuthoringCheckpoint | None = None,
    stage: AuthoringStageWriter | None = None,
) -> DocumentAuthoringResult:
    """Author an outline and bounded sections with one shared protocol repair."""

    if resume is None and evidence is not None and not evidence.project_context().complete:
        return DocumentAuthoringResult(None, "evidence_incomplete", failure_stage="outline")
    if resume is None:
        if stage is not None:
            await stage("outline")
        outline, repair_used, outline_rejection = await _outline_with_single_repair(
            intent,
            model,
            execution=execution,
            citations=citations,
            evidence=evidence,
        )
    else:
        outline, repair_used = resume.outline, resume.repair_used
        outline_rejection = None
    if outline is None:
        return DocumentAuthoringResult(
            None,
            "draft_protocol",
            repair_used=True,
            failure_stage="outline",
            rejection_reason=outline_rejection or "response_missing",
        )
    accepted_ids = list(resume.accepted_section_ids if resume is not None else ())
    blocks: list[DraftBlock] = list(resume.blocks if resume is not None else ())
    draft_version = resume.draft_version if resume is not None else 1
    if checkpoint is not None:
        await checkpoint(
            DocumentAuthoringCheckpoint(
                "outline" if not accepted_ids else "section_authoring",
                outline,
                tuple(blocks),
                tuple(accepted_ids),
                repair_used,
                draft_version=draft_version,
            )
        )

    if stage is not None and any(
        section.section_id not in accepted_ids for section in outline.sections
    ):
        await stage("section_authoring")
    for section in outline.sections:
        if section.section_id in accepted_ids:
            continue
        if intent.kind == "article" and section_role(section.title) == "references":
            # Bibliography content and heading are rendered from the trusted
            # citation registry; the model never authors a second references list.
            accepted_ids.append(section.section_id)
            if checkpoint is not None:
                await checkpoint(
                    DocumentAuthoringCheckpoint(
                        "section_authoring",
                        outline,
                        tuple(blocks),
                        tuple(accepted_ids),
                        repair_used,
                        draft_version=draft_version,
                    )
                )
            continue
        authored, failure, rejection = await _invoke_section_round(
            intent,
            outline,
            section,
            model,
            execution=execution,
            citations=citations,
            evidence=evidence,
            repair=False,
        )
        if authored is None and failure != "evidence_incomplete" and not repair_used:
            repair_used = True
            authored, failure, rejection = await _invoke_section_round(
                intent,
                outline,
                section,
                model,
                execution=execution,
                citations=citations,
                evidence=evidence,
                repair=True,
            )
        if authored is None:
            partial = (
                DocumentDraft(1, draft_version, outline.title, tuple(blocks)) if blocks else None
            )
            return DocumentAuthoringResult(
                partial,
                failure or "draft_protocol",
                repair_used=repair_used,
                accepted_sections=len(accepted_ids),
                failure_stage="section_authoring",
                rejection_reason=rejection,
            )
        blocks.extend(authored)
        accepted_ids.append(section.section_id)
        if checkpoint is not None:
            await checkpoint(
                DocumentAuthoringCheckpoint(
                    "section_authoring",
                    outline,
                    tuple(blocks),
                    tuple(accepted_ids),
                    repair_used,
                    draft_version=draft_version,
                )
            )

    draft = DocumentDraft(1, draft_version, outline.title, tuple(blocks))
    if checkpoint is not None:
        await checkpoint(
            DocumentAuthoringCheckpoint(
                "complete",
                outline,
                tuple(blocks),
                tuple(accepted_ids),
                repair_used,
                draft_version=draft_version,
            )
        )
    return DocumentAuthoringResult(
        draft,
        repair_used=repair_used,
        accepted_sections=len(accepted_ids),
    )


async def author_semantic_draft(
    intent: DocumentIntent,
    model: str,
    *,
    execution: RunExecutionContext,
    citations: CitationRegistry | None,
    evidence: DocumentEvidenceBundle | None = None,
    checkpoint: CheckpointWriter | None = None,
    resume: DocumentAuthoringCheckpoint | None = None,
    stage: AuthoringStageWriter | None = None,
) -> DocumentDraft | None:
    result = await author_semantic_draft_result(
        intent,
        model,
        execution=execution,
        citations=citations,
        evidence=evidence,
        checkpoint=checkpoint,
        resume=resume,
        stage=stage,
    )
    return result.draft


__all__ = [
    "DocumentAuthoringCheckpoint",
    "DocumentAuthoringResult",
    "author_semantic_draft",
    "author_semantic_draft_result",
    "repair_semantic_draft",
    "restore_authoring_checkpoint",
    "resolve_document_intent",
]
