"""Safe and deterministic projection of tool-round state into existing AgentEvents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from service.events import AgentEvent, EventType

from .contracts import ToolCallOutcome


@dataclass(frozen=True, slots=True)
class ToolRoundEventProjector:
    agent_name: str
    round_number: int

    def plan(self, calls: list[dict[str, Any]]) -> AgentEvent:
        return AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name=self.agent_name,
            data="",
            metadata={
                "kind": "tool_plan",
                "tool_plan": {
                    "round": self.round_number,
                    "tools": [str(call.get("name") or "external_tool") for call in calls],
                    "status": "pending",
                },
            },
        )

    def start(self, call: dict[str, Any]) -> tuple[AgentEvent, AgentEvent]:
        name = str(call.get("name") or "external_tool")
        progress = {
            "tool": name,
            "round": self.round_number,
            "status": "running",
        }
        return (
            AgentEvent(
                type=EventType.TOOL_CALL_START,
                agent_name=self.agent_name,
                data=f"Вызываю инструмент: {name}",
                metadata={"tool_name": name, "tool_progress": progress},
            ),
            AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=self.agent_name,
                data="",
                metadata={"kind": "tool_progress", "tool_progress": progress},
            ),
        )

    def completion(
        self,
        call: dict[str, Any],
        outcome: ToolCallOutcome,
        *,
        result_chars: int,
        compaction: dict[str, Any],
        billing_metadata: dict[str, Any] | None,
    ) -> tuple[AgentEvent, AgentEvent]:
        name = str(call.get("name") or "external_tool")
        status = "reused" if outcome.reused else outcome.status
        progress = {
            "tool": name,
            "round": self.round_number,
            "status": status,
            "duration_ms": round(outcome.duration_sec * 1000),
            "result_chars": max(0, int(result_chars)),
            "compacted": bool(compaction.get("applied")),
            "dedup_observed": bool(outcome.dedup_observed),
            "dedup_reason": outcome.dedup_reason,
            "retryable": bool(outcome.retryable),
            "failure_code": outcome.failure_code,
            "billing": outcome.billing_disposition,
        }
        metadata = {
            **(billing_metadata or {}),
            "tool_name": name,
            "tool_progress": progress,
        }
        if compaction.get("applied"):
            metadata["compaction"] = compaction
        description = f"{name} · {result_chars} симв."
        if compaction.get("applied"):
            description += f" → {compaction.get('after', 0)} (сжато)"
        return (
            AgentEvent(
                type=EventType.TOOL_CALL_COMPLETE,
                agent_name=self.agent_name,
                data=description,
                metadata=metadata,
            ),
            AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=self.agent_name,
                data="",
                metadata={"kind": "tool_progress", "tool_progress": progress},
            ),
        )

    @staticmethod
    def update_summary(summary: dict[str, Any] | None, outcome: ToolCallOutcome) -> None:
        if summary is None:
            return
        if outcome.reused:
            summary["reused"] = int(summary.get("reused", 0)) + 1
        else:
            summary["executed"] = int(summary.get("executed", 0)) + 1
        if outcome.dedup_observed:
            summary["dedup_observed"] = int(summary.get("dedup_observed", 0)) + 1
        status = "reused" if outcome.reused else outcome.status
        if status != "reused":
            summary[status] = int(summary.get(status, 0)) + 1
        if outcome.failure_code:
            failures = summary.setdefault("failure_codes", {})
            failures[outcome.failure_code] = int(failures.get(outcome.failure_code, 0)) + 1


__all__ = ["ToolRoundEventProjector"]
