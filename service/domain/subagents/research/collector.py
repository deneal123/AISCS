"""Concurrent fail-soft evidence collection with no sensitive progress payloads."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from service.shared import deadline

from .models import CollectionStats, ResearchPlan
from .sources import SourceRegistry, normalize_url

Search = Callable[..., Awaitable[list[dict[str, Any]]]]
Read = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class CollectedEvidence:
    registry: SourceRegistry
    stats: CollectionStats


async def _search_safe(
    query: str,
    *,
    search: Search,
    timeout_sec: float,
) -> tuple[list[dict[str, Any]], bool, bool]:
    if deadline.must_finalize():
        return [], False, True
    try:
        results = await asyncio.wait_for(
            search(query, num_results=4),
            timeout=deadline.clamp(timeout_sec),
        )
    except (TimeoutError, Exception):  # noqa: BLE001
        return [], True, False
    safe = [item for item in results or [] if isinstance(item, dict)]
    return safe, False, False


def _unique_results(per_query: list[list[dict[str, Any]]], limit: int = 12) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for results in per_query:
        for result in results:
            canonical = normalize_url(result.get("url"))
            if canonical is None or canonical in seen:
                continue
            seen.add(canonical)
            unique.append(result)
            if len(unique) >= limit:
                return unique
    return unique


async def _read_safe(
    result: dict[str, Any],
    *,
    read: Read,
    gate: asyncio.Semaphore,
    timeout_sec: float,
) -> tuple[dict[str, Any], bool, bool]:
    if deadline.must_finalize():
        return {}, False, True
    async with gate:
        try:
            page = await asyncio.wait_for(
                read(str(result.get("url") or ""), max_chars=4000),
                timeout=deadline.clamp(timeout_sec),
            )
        except (TimeoutError, Exception):  # noqa: BLE001
            return {}, True, False
    return (page if isinstance(page, dict) else {}), False, False


def _register_result(
    registry: SourceRegistry,
    result: dict[str, Any],
    page: dict[str, Any],
) -> bool:
    page_content = str(page.get("content") or "").strip()
    snippet = str(result.get("snippet") or "").strip()
    content = page_content if len(page_content) >= 20 else snippet
    kind = "page" if len(page_content) >= 20 else "snippet"
    record = registry.add(
        url=result.get("url"),
        title=page.get("title") or result.get("title"),
        content=content,
        content_kind=kind,
    )
    return record is not None


async def collect_evidence(
    plan: ResearchPlan,
    *,
    search: Search,
    read: Read,
    search_timeout_sec: float,
    read_timeout_sec: float = 10.0,
    max_sources: int = 12,
) -> CollectedEvidence:
    """Collect partial evidence without aborting the whole report."""

    searched = await asyncio.gather(
        *(
            _search_safe(query, search=search, timeout_sec=search_timeout_sec)
            for query in plan.queries
        )
    )
    per_query = [item[0] for item in searched]
    search_failures = sum(1 for _, failed, _ in searched if failed)
    deadline_stops = sum(1 for _, _, stopped in searched if stopped)
    results = _unique_results(per_query, max_sources)
    registry = SourceRegistry(max_sources=max_sources)
    if not results:
        return CollectedEvidence(
            registry,
            CollectionStats(
                query_count=plan.query_count,
                result_count=sum(len(items) for items in per_query),
                search_failures=search_failures,
                deadline_stops=deadline_stops,
            ),
        )
    gate = asyncio.Semaphore(4)
    read_results = await asyncio.gather(
        *(
            _read_safe(
                result,
                read=read,
                gate=gate,
                timeout_sec=read_timeout_sec,
            )
            for result in results
        )
    )
    read_failures = 0
    for result, (page, failed, stopped) in zip(results, read_results, strict=True):
        if failed:
            read_failures += 1
        if stopped:
            deadline_stops += 1
        # A readable search snippet remains useful when a page is blocked.
        if not _register_result(registry, result, page) and not stopped:
            read_failures += 1
    return CollectedEvidence(
        registry,
        CollectionStats(
            query_count=plan.query_count,
            result_count=sum(len(items) for items in per_query),
            source_count=len(registry.records),
            read_failures=read_failures,
            search_failures=search_failures,
            deadline_stops=deadline_stops,
        ),
    )


__all__ = ["CollectedEvidence", "collect_evidence"]
