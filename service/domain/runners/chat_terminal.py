"""Terminal event construction for the chat-completions runner."""

from __future__ import annotations

from typing import Any

from service.events import AgentEvent, EventType

_TOOL_CAP_MESSAGE = (
    "Не удалось довести задачу до ответа за отведённое число шагов с инструментами. "
    "Попробуйте переформулировать запрос или разбить его на части."
)


def tool_cap_message() -> str:
    """Explain a tool-round cap without presenting it as a provider failure."""
    return _TOOL_CAP_MESSAGE


def completed_event(
    agent_name: str, model: str, usage: dict, summary: dict[str, Any]
) -> AgentEvent:
    """Construct the sole successful terminal event for a streamed chat run."""
    return AgentEvent(
        type=EventType.AGENT_COMPLETE,
        agent_name=agent_name,
        data=f"Completed {agent_name}",
        metadata={"model": model, "token_usage": usage, "tool_summary": summary},
    )
