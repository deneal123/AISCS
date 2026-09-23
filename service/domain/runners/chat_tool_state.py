"""Small state transitions extracted from the streamed tool loop."""

from __future__ import annotations

from typing import Any

from service.domain.runners.chat_budget import prompt_budget_stop
from service.events import AgentEvent, EventType

_FINALIZE_NUDGE = (
    "Время на этот запрос заканчивается. Ответь тем, что уже есть, не вызывая инструменты. "
    "Если данных не хватило — скажи об этом прямо."
)


def deadline_finalization(
    convo: list[dict], *, agent_name: str, round_number: int, summary: dict[str, Any]
) -> tuple[AgentEvent, list[dict]]:
    summary["deadline_finalized"] = True
    return (
        AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name=agent_name,
            data="",
            metadata={
                "kind": "tool_progress",
                "tool_progress": {
                    "status": "skipped",
                    "reason": "deadline_finalized",
                    "round": round_number,
                },
            },
        ),
        convo + [{"role": "user", "content": _FINALIZE_NUDGE}],
    )


def should_finalize(tool_calls: list, *, finalizing: bool, deadline_reached: bool) -> bool:
    return bool(tool_calls) and deadline_reached and not finalizing


def model_unavailable_event(agent_name: str) -> AgentEvent:
    return AgentEvent(
        type=EventType.ERROR,
        agent_name=agent_name,
        data="Нет доступной модели для обработки запроса",
    )


def initial_tool_summary(toolset) -> dict[str, int]:
    return {
        "offered": len(toolset.tools),
        "omitted": len(toolset.omissions),
        "executed": 0,
        "succeeded": 0,
        "failed": 0,
    }


def exceeds_prompt_budget(*, budget: int, spent: int, next_prompt: int) -> bool:
    return bool(budget) and spent + next_prompt > budget


def prompt_budget_events(
    summary: dict[str, Any],
    *,
    budget: int,
    estimated: int,
    round_number: int,
    agent_name: str,
    model: str,
) -> tuple[list[AgentEvent], str]:
    event, safety_note = prompt_budget_stop(
        summary,
        budget=budget,
        estimated=estimated,
        round_number=round_number,
        agent_name=agent_name,
    )
    return (
        [
            event,
            AgentEvent(
                type=EventType.STREAM_CHUNK,
                agent_name=agent_name,
                data=safety_note,
                metadata={"model": model},
            ),
        ],
        safety_note,
    )


def tool_round_cap_events(
    tool_calls: list, *, summary: dict[str, Any], agent_name: str, round_number: int
) -> list[AgentEvent]:
    if not tool_calls:
        return []
    summary["round_cap_reached"] = True
    summary["skipped"] = int(summary.get("skipped", 0)) + len(tool_calls)
    return [
        AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name=agent_name,
            data="",
            metadata={
                "kind": "tool_progress",
                "tool_progress": {
                    "status": "skipped",
                    "reason": "round_cap_reached",
                    "round": round_number,
                },
            },
        )
    ]


def compact_workspace_context(convo: list[dict], tool_calls: list, context: Any | None) -> bool:
    if not any(
        str(call.get("function", {}).get("name") or "").startswith("ws_")
        for call in tool_calls
        if isinstance(call, dict)
    ):
        return False
    system_context = str(getattr(context, "system_context", "") or "")
    current = str(convo[0].get("content") or "")
    if not system_context or (
        "# Graph Report" not in system_context and "# Файлы архива (" not in system_context
    ):
        return False
    prefix = current.removesuffix(system_context).rstrip()
    if prefix == current.rstrip():
        return False
    convo[0] = {
        **convo[0],
        "content": (
            f"{prefix}\n\n## Контекст архива\n"
            "Карта репозитория уже использована для выбора инструментов. Дальше опирайся на "
            "результаты workspace-инструментов и при необходимости исследуй нужные файлы ими."
        ),
    }
    return True
