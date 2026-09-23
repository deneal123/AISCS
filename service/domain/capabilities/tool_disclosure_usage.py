"""Compatibility projection of selector usage into the existing event contract."""

from __future__ import annotations

from typing import Any

from service.domain.usage_tracking import is_billable
from service.events import AgentEvent, EventType


def usage_event(usage: dict[str, Any] | None, agent_name: str) -> AgentEvent | None:
    if not is_billable(usage):
        return None
    assert usage is not None
    token_usage = {
        "prompt": usage.get("prompt", 0),
        "completion": usage.get("completion", 0),
        "total": usage.get("total", 0),
        "model": usage.get("model"),
    }
    for key in ("provider", "calls", "estimated"):
        if usage.get(key):
            token_usage[key] = usage[key]
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name=agent_name,
        data="",
        metadata={"kind": "meta_usage", "token_usage": token_usage},
    )


__all__ = ["usage_event"]
