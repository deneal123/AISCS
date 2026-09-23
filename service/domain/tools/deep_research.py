"""Compatibility facade for the evidence-first native research pipeline."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from service.domain.client import create_chat_completion
from service.domain.subagents.research import (
    ResearchDependencies,
    ResearchProgress,
    run_native_research,
)
from service.domain.subagents.research.synthesis import _SYNTHESIS_SYSTEM
from service.domain.tools.web_search import parse_url, search_budget_sec, web_search

# Compatibility template kept for prompt-contract tests and external imports. Runtime
# uses the same shared text in ``research.synthesis``.
_SYNTHESIS_PROMPT = _SYNTHESIS_SYSTEM + "\n\nТема: {topic}\n\nСобранные данные:\n{data}"


def _wrap(prompt: str, slot: str) -> str:
    """Compatibility hook for the shared persona contract."""

    from service.domain import persona

    return persona.current().wrap(prompt, slot)


async def deep_research(
    topic: str,
    model: str,
) -> AsyncGenerator[str | ResearchProgress]:
    """Run research while preserving the historical generator contract."""

    dependencies = ResearchDependencies(
        completion=create_chat_completion,
        search=web_search,
        read=parse_url,
        search_timeout=search_budget_sec,
    )
    async for item in run_native_research(
        topic,
        model,
        dependencies=dependencies,
    ):
        yield item


__all__ = ["ResearchProgress", "_SYNTHESIS_PROMPT", "_wrap", "deep_research"]
