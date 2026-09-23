"""Run-scoped progressive tool disclosure state.

The controller owns only the optimization after policy resolution.  It cannot
authorize a tool and it deliberately records names/statuses, never tool output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from service.domain.capabilities.tool_disclosure import disclose, usage_event
from service.domain.capabilities.tool_registry import get_tool_spec
from service.domain.capabilities.tool_spec import ToolSet
from service.domain.run_context import RunExecutionContext
from service.events import AgentEvent, EventType


@dataclass(slots=True)
class DisclosureUpdate:
    toolset: ToolSet
    events: list[AgentEvent]
    estimated_prompt_tokens: int
    preferred_tool: str | None = None
    grounding_required: bool = False

    @property
    def tool_choice(self) -> dict[str, Any] | None:
        if not self.preferred_tool:
            return None
        return {"type": "function", "function": {"name": self.preferred_tool}}


@dataclass(slots=True)
class ToolSelectionController:
    eligible_toolset: ToolSet
    question: str
    agent_name: str
    context: Any | None
    preferred_model: str
    execution: RunExecutionContext
    executed: list[dict[str, str]] = field(default_factory=list)

    @property
    def tool_index(self) -> dict[str, Any]:
        index: dict[str, Any] = {}
        for serialized in self.eligible_toolset.tools:
            name = str((serialized.get("function") or {}).get("name") or "")
            if spec := get_tool_spec(name):
                index[name] = spec.tool
        return index

    def record(self, event: AgentEvent) -> None:
        progress = (event.metadata or {}).get("tool_progress")
        if (
            event.type == EventType.TOOL_CALL_COMPLETE
            and isinstance(progress, dict)
            and progress.get("status") in {"succeeded", "failed", "reused"}
            and progress.get("tool")
        ):
            self.executed.append({"tool": str(progress["tool"]), "status": str(progress["status"])})

    async def select(self, *, stage: int, remaining_prompt_tokens: int | None) -> DisclosureUpdate:
        result = await disclose(
            self.eligible_toolset,
            question=self.question,
            agent_name=self.agent_name,
            context=self.context,
            preferred_model=self.preferred_model,
            stage=stage,
            executed=list(self.executed),
            remaining_prompt_tokens=remaining_prompt_tokens,
            execution=self.execution,
        )
        events: list[AgentEvent] = []
        if result.event is not None:
            events.append(result.event)
        if result.intent_event is not None:
            events.append(result.intent_event)
        if event := usage_event(result.usage, self.agent_name):
            events.append(event)
        if stage == 1:
            offered_names = []
            for item in result.toolset.tools:
                if isinstance(item, dict):
                    name = str((item.get("function") or {}).get("name") or "")
                else:
                    name = str(getattr(item, "name", "") or "")
                if name:
                    offered_names.append(name)
            self.execution.grounding.configure(
                requirement=self.execution.policy.grounding_reason,
                preferred_tool=result.preferred_tool,
                offered_names=offered_names,
                candidate_count=len(self.eligible_toolset.tools),
            )
            if result.intent_event is not None:
                intent = (result.intent_event.metadata or {}).get("tool_intent")
                if isinstance(intent, dict):
                    intent.update(self.execution.grounding.bounded_metadata())
        return DisclosureUpdate(
            toolset=result.toolset,
            events=events,
            estimated_prompt_tokens=result.estimated_prompt_tokens,
            preferred_tool=(result.preferred_tool if stage == 1 else None),
            grounding_required=result.grounding_required,
        )


# Compatibility import for older tests and extensions. Selection now owns both tiering
# and deterministic grounding; there is deliberately no second selector.
ToolDisclosureController = ToolSelectionController
