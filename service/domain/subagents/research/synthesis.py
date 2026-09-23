"""Evidence synthesis, deterministic audit, and one budgeted repair pass."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from service.domain.llm_response import first_message_content
from service.domain.model_runtime import invoke_model_call
from service.domain.subagents.runtime import StageContext, StageRuntime
from service.domain.subagents.web_search import _SOURCE_DISCIPLINE
from service.domain.usage_ledger import UsageKind
from service.shared import deadline

from .audit import CitationAudit, audit_citations, strip_invalid_citations
from .sources import SourceRegistry

Completion = Callable[..., Awaitable[Any]]

_SYNTHESIS_SYSTEM = (
    """Ты — ведущий аналитик. Подготовь практичный отчёт на русском.

Используй только факты из реестра источников ниже. Ссылка на источник обозначается
строго его номером [n]. Не придумывай номера, URL или источники. Каждый содержательный
фактический абзац должен иметь хотя бы одну цитату. Если данные противоречат друг другу
или их недостаточно, скажи это прямо.

"""
    + _SOURCE_DISCIPLINE
    + """

Структура: TL;DR, Контекст, Основные факты, Сравнение точек зрения, Риски и ограничения,
Практические рекомендации, Итог. Не добавляй раздел источников: он будет построен
детерминированно из реестра.
"""
)

_REPAIR_SYSTEM = """Исправь только цитирование отчёта.

Разрешены только номера источников из переданного реестра. Удали неподтверждённые факты,
замени несуществующие цитаты и поставь цитаты в фактические абзацы. Не добавляй URL,
новые источники, новые факты или комментарий о правке. Верни только исправленный отчёт.
"""


def _persona_synthesis(text: str) -> str:
    from service.domain import persona

    return persona.current().wrap(text, "research.synthesis")


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    body: str
    audit: CitationAudit
    repair_used: bool
    partial: bool


async def _completion_stage(
    *,
    stage_name: str,
    system: str,
    user: str,
    model: str,
    completion: Completion,
    stages: StageContext,
    usage_kind: UsageKind,
    max_tokens: int,
):
    async def _call():
        return await invoke_model_call(
            completion,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model,
            kind=usage_kind,
            temperature=0.35 if usage_kind is UsageKind.RESEARCH_SYNTHESIS else 0.1,
            max_tokens=max_tokens,
        )

    return await StageRuntime(
        stages,
        stage=stage_name,
        timeout_sec=150,
        input_count=1,
    ).run_model(_call)


async def synthesize_report(
    topic: str,
    registry: SourceRegistry,
    *,
    model: str,
    completion: Completion,
    stages: StageContext,
    allow_repair: bool = True,
) -> SynthesisResult:
    context = registry.synthesis_context()
    initial = await _completion_stage(
        stage_name="research_synthesis",
        system=_persona_synthesis(_SYNTHESIS_SYSTEM),
        user=f"Тема:\n{topic}\n\nРеестр:\n{context}",
        model=model,
        completion=completion,
        stages=stages,
        usage_kind=UsageKind.RESEARCH_SYNTHESIS,
        max_tokens=3000,
    )
    body = first_message_content(initial.value).strip() if initial.ok else ""
    if not body:
        return SynthesisResult("", audit_citations("", registry), False, True)
    audit = audit_citations(body, registry)
    if audit.valid or not allow_repair or deadline.must_finalize():
        return SynthesisResult(
            strip_invalid_citations(body, registry),
            audit,
            False,
            not audit.valid,
        )
    repaired = await _completion_stage(
        stage_name="research_repair",
        system=_REPAIR_SYSTEM,
        user=f"Реестр:\n{context}\n\nОтчёт:\n{body}",
        model=model,
        completion=completion,
        stages=stages,
        usage_kind=UsageKind.RESEARCH_REPAIR,
        max_tokens=3000,
    )
    repaired_body = first_message_content(repaired.value).strip() if repaired.ok else ""
    if not repaired_body:
        return SynthesisResult(strip_invalid_citations(body, registry), audit, True, True)
    repaired_audit = audit_citations(repaired_body, registry)
    return SynthesisResult(
        strip_invalid_citations(repaired_body, registry),
        repaired_audit,
        True,
        not repaired_audit.valid,
    )


__all__ = ["SynthesisResult", "synthesize_report"]
