"""Composable native research pipeline used by the compatibility tool facade."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass

from service.domain.run_context import current_execution
from service.domain.subagents.runtime import StageContext
from service.shared import deadline

from .collector import Read, Search, collect_evidence
from .models import ResearchProgress, ResearchReport, ResearchStatus
from .planner import Completion, plan_queries
from .synthesis import synthesize_report


@dataclass(frozen=True, slots=True)
class ResearchDependencies:
    completion: Completion
    search: Search
    read: Read
    search_timeout: Callable[[], float]


def _no_sources_report(stats) -> ResearchReport:
    body = (
        "Внешние источники по теме сейчас недоступны: поиск не вернул пригодных "
        "результатов или страницы не удалось прочитать.\n\n"
        "### Что можно сделать дальше\n"
        "1. Уточнить язык, страну и период.\n"
        "2. Повторить позже при временной недоступности источников.\n"
        "3. Передать конкретные ссылки для отдельного разбора."
    )
    return ResearchReport(
        body=body,
        sources_section="### Источники",
        status=ResearchStatus.NO_SOURCES,
        collection=stats,
    )


def _evidence_fallback(registry) -> str:
    lines = [
        "Синтез отчёта недоступен. Ниже сохранена проверяемая выжимка из полученных источников:"
    ]
    for record in registry.records:
        lines.append(f"- **{record.title}** [{record.source_id}] — {record.content[:320]}")
    return "\n".join(lines)


async def run_native_research(
    topic: str,
    model: str,
    *,
    dependencies: ResearchDependencies,
) -> AsyncGenerator[str | ResearchProgress]:
    stages = StageContext()
    yield ResearchProgress(5, "Составляю план исследования", stage="planning")
    plan = await plan_queries(
        topic,
        model,
        completion=dependencies.completion,
        stages=stages,
    )
    yield ResearchProgress(
        15,
        f"План готов: направлений поиска — {plan.query_count}",
        stage="planning",
        status="partial" if plan.fallback else "succeeded",
    )
    yield ResearchProgress(
        25,
        f"Ищу источники по направлениям: {plan.query_count}",
        stage="collection",
    )
    evidence = await collect_evidence(
        plan,
        search=dependencies.search,
        read=dependencies.read,
        search_timeout_sec=dependencies.search_timeout(),
    )
    stats = evidence.stats
    execution = current_execution()
    if execution is not None:
        execution.artifacts.publish(
            "research.latest",
            evidence.registry.artifact(status="partial" if stats.partial else "ready"),
            replace=True,
        )
    yield ResearchProgress(
        55,
        f"Найдено источников: {stats.result_count}",
        stage="collection",
        status="partial" if stats.partial else "succeeded",
    )
    yield ResearchProgress(
        65,
        f"Читаю источники: {stats.source_count}",
        stage="collection",
    )
    yield ResearchProgress(
        80,
        (
            f"Проанализировано источников: {stats.source_count}"
            + (f", недоступно — {stats.read_failures}" if stats.read_failures else "")
        ),
        stage="collection",
        status="partial" if stats.partial else "succeeded",
    )
    if not evidence.registry.records:
        report = _no_sources_report(stats)
        yield ResearchProgress(90, "Готовлю частичный ответ", stage="synthesis", status="partial")
        yield report.text
        return
    if deadline.must_finalize():
        report = ResearchReport(
            body=_evidence_fallback(evidence.registry),
            sources_section=evidence.registry.sources_section(),
            status=ResearchStatus.DEADLINE,
            collection=stats,
        )
        yield ResearchProgress(
            90,
            "Формирую частичный результат",
            stage="synthesis",
            status="deadline",
            failure_code="deadline",
        )
        yield report.text
        return
    yield ResearchProgress(90, "Синтезирую отчёт", stage="synthesis")
    synthesis = await synthesize_report(
        topic,
        evidence.registry,
        model=model,
        completion=dependencies.completion,
        stages=stages,
    )
    body = synthesis.body or _evidence_fallback(evidence.registry)
    status = (
        ResearchStatus.PARTIAL if synthesis.partial or stats.partial else ResearchStatus.SUCCEEDED
    )
    report = ResearchReport(
        body=body,
        sources_section=evidence.registry.sources_section(),
        status=status,
        collection=stats,
        citation_valid=synthesis.audit.valid,
        repair_used=synthesis.repair_used,
    )
    yield report.text


__all__ = ["ResearchDependencies", "run_native_research"]
