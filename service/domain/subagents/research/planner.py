"""Strict research-query planner; query text remains internal to collection."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from service.domain.json_fence import strip_json_fence
from service.domain.llm_response import first_message_content
from service.domain.model_runtime import invoke_model_call
from service.domain.subagents.runtime import StageContext, StageRuntime
from service.domain.usage_ledger import UsageKind

from .models import ResearchPlan

Completion = Callable[..., Awaitable[Any]]

_PLAN_PROMPT = (
    "Составь 4 поисковых запроса для системного исследования темы. Покрой факты и "
    "контекст, актуальные данные, критику и риски, практические кейсы. Сохрани все "
    "имена, даты и ограничения темы. Верни ТОЛЬКО JSON-массив строк."
)


def _persona_prompt(text: str, slot: str) -> str:
    from service.domain import persona

    return persona.current().wrap(text, slot)


def fallback_queries(topic: str) -> tuple[str, ...]:
    value = re.sub(r"\s+", " ", str(topic or "")).strip()[:1200]
    return (
        value,
        f"{value} обзор и факты",
        f"{value} актуальные данные",
        f"{value} критика риски примеры",
    )


def parse_plan(raw: str, topic: str) -> ResearchPlan:
    try:
        parsed = json.loads(strip_json_fence(raw) or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return ResearchPlan(fallback_queries(topic), fallback=True)
    if not isinstance(parsed, list):
        return ResearchPlan(fallback_queries(topic), fallback=True)
    queries: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        query = re.sub(r"\s+", " ", str(item or "")).strip()[:600]
        key = query.casefold()
        if len(query) < 3 or key in seen:
            continue
        seen.add(key)
        queries.append(query)
        if len(queries) >= 6:
            break
    if not queries:
        return ResearchPlan(fallback_queries(topic), fallback=True)
    return ResearchPlan(tuple(queries[:4]), fallback=False)


async def plan_queries(
    topic: str,
    model: str,
    *,
    completion: Completion,
    stages: StageContext,
) -> ResearchPlan:
    async def _call():
        return await invoke_model_call(
            completion,
            messages=[
                {"role": "system", "content": "Ты помощник. Отвечай ТОЛЬКО JSON."},
                {
                    "role": "user",
                    "content": _persona_prompt(
                        f"{_PLAN_PROMPT}\n\nТема:\n{topic}", "research.plan"
                    ),
                },
            ],
            model=model,
            kind=UsageKind.RESEARCH_PLAN,
            temperature=0.3,
            max_tokens=500,
        )

    outcome = await StageRuntime(
        stages,
        stage="research_plan",
        timeout_sec=60,
        input_count=1,
    ).run_model(_call)
    if not outcome.ok or outcome.value is None:
        return ResearchPlan(fallback_queries(topic), fallback=True)
    return parse_plan(first_message_content(outcome.value), topic)


__all__ = ["fallback_queries", "parse_plan", "plan_queries"]
