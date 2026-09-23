"""Prompt-budget boundary handling for streamed chat runs."""

from __future__ import annotations

from typing import Any

from service.events import AgentEvent, EventType

_SAFETY_NOTE = (
    "\n\nЗапрос остановлен до следующего вызова модели: достигнут лимит стоимости для одного "
    "запуска. Сузьте задачу или разбейте её на части."
)


def prompt_budget_stop(
    summary: dict[str, Any], *, budget: int, estimated: int, round_number: int, agent_name: str
) -> tuple[AgentEvent, str]:
    """Record a preflight stop and return its safe user-visible explanation."""
    summary["prompt_budget_reached"] = True
    summary["prompt_budget_tokens"] = budget
    summary["estimated_prompt_tokens"] = estimated
    return (
        AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name=agent_name,
            data="",
            metadata={
                "kind": "tool_progress",
                "tool_progress": {
                    "status": "skipped",
                    "reason": "prompt_budget_reached",
                    "round": round_number,
                },
            },
        ),
        _SAFETY_NOTE,
    )
