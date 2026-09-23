"""Run-scoped latch for deterministic, policy-approved tool grounding."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from service.domain.capabilities.tool_registry import tool_grounding_roles
from service.domain.capabilities.tool_spec import (
    GROUNDING_FRESH_DATA,
    GROUNDING_REPOSITORY,
    GROUNDING_TABULAR,
    GROUNDING_WORKSPACE,
)


class GroundingState(StrEnum):
    INACTIVE = "inactive"
    PENDING = "pending"
    REPAIR = "repair"
    SATISFIED = "satisfied"
    FAILED = "failed"


class GroundingFailureCode(StrEnum):
    NONE = ""
    NO_ELIGIBLE_TOOLS = "no_eligible_tools"
    MISSING_CALL = "missing_call"
    WRONG_CALL = "wrong_call"
    INVALID_ARGUMENTS = "invalid_arguments"
    TOOL_FAILURE = "tool_failure"
    PROVIDER_FAILURE = "provider_failure"
    DEADLINE = "deadline"
    PROMPT_BUDGET = "prompt_budget"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


_REQUIREMENT_ROLES = {
    "workspace_explicit": frozenset({GROUNDING_WORKSPACE}),
    "workspace_source_only": frozenset({GROUNDING_WORKSPACE, GROUNDING_REPOSITORY}),
    "fresh_data": frozenset({GROUNDING_FRESH_DATA}),
    "tabular_source_only": frozenset({GROUNDING_TABULAR}),
}
_INVALID_FAILURES = frozenset({"invalid_json", "invalid_arguments"})
_SUCCESS_STATUSES = frozenset({"succeeded", "reused"})


@dataclass(slots=True)
class GroundingLatch:
    """Accept a final answer only after the required tool actually succeeded.

    The preferred name is private run state. Trace projection exposes only booleans,
    counts, attempts, states, and closed reason codes.
    """

    state: GroundingState = GroundingState.INACTIVE
    requirement: str = ""
    preferred_tool: str | None = None
    eligible_names: frozenset[str] = frozenset()
    eligible_roles: frozenset[str] = frozenset()
    candidate_count: int = 0
    offered_count: int = 0
    attempt: int = 0
    repair_count: int = 0
    failure_code: GroundingFailureCode = GroundingFailureCode.NONE
    _round_target_seen: bool = False
    _round_any_call: bool = False
    _round_invalid: bool = False
    _round_failed: bool = False
    _round_names: set[str] = field(default_factory=set)

    @property
    def required(self) -> bool:
        return self.state is not GroundingState.INACTIVE

    @property
    def blocks_output(self) -> bool:
        return self.state in {GroundingState.PENDING, GroundingState.REPAIR}

    @property
    def forced(self) -> bool:
        return self.blocks_output and self.preferred_tool is not None

    def configure(
        self,
        *,
        requirement: Any,
        preferred_tool: str | None,
        offered_names: list[str],
        candidate_count: int,
    ) -> None:
        value = str(getattr(requirement, "value", requirement) or "")
        if not value:
            self.state = GroundingState.INACTIVE
            return
        self.requirement = value
        self.preferred_tool = str(preferred_tool) if preferred_tool else None
        self.candidate_count = max(0, int(candidate_count))
        self.offered_count = len(offered_names)
        allowed_roles = _REQUIREMENT_ROLES.get(value, frozenset())
        self.eligible_roles = allowed_roles
        eligible = {name for name in offered_names if tool_grounding_roles(name) & allowed_roles}
        if self.preferred_tool and self.preferred_tool in offered_names:
            eligible.add(self.preferred_tool)
        self.eligible_names = frozenset(eligible)
        self.state = GroundingState.PENDING
        self.failure_code = GroundingFailureCode.NONE
        self._reset_round()
        if not self.eligible_names:
            self.fail(GroundingFailureCode.NO_ELIGIBLE_TOOLS)

    def accepts(self, tool_name: str) -> bool:
        name = str(tool_name or "")
        if self.preferred_tool:
            return name == self.preferred_tool
        return name in self.eligible_names

    def begin_round(self) -> None:
        if not self.blocks_output:
            return
        self.attempt += 1
        self._reset_round()

    def observe_call(self, tool_name: str) -> None:
        if not self.blocks_output:
            return
        name = str(tool_name or "")
        self._round_any_call = True
        self._round_names.add(name)
        if self.accepts(name):
            self._round_target_seen = True

    def observe_outcome(self, tool_name: str, outcome: Any) -> None:
        if not self.blocks_output or not self.accepts(tool_name):
            return
        self._round_target_seen = True
        status = str(getattr(outcome, "status", ""))
        failure = str(getattr(outcome, "failure_code", ""))
        reused = bool(getattr(outcome, "reused", False))
        succeeded = bool(getattr(outcome, "succeeded", False))
        if succeeded or (reused and status in _SUCCESS_STATUSES):
            self.state = GroundingState.SATISFIED
            self.failure_code = GroundingFailureCode.NONE
            return
        if status == "invalid" or failure in _INVALID_FAILURES:
            self._round_invalid = True
            return
        self._round_failed = True

    def finish_model_round(self, tool_calls: list[dict[str, Any]]) -> GroundingState:
        if not self.blocks_output:
            return self.state
        for call in tool_calls:
            if isinstance(call, dict):
                self.observe_call(str(call.get("name") or ""))
        if not tool_calls:
            return self._repair_or_fail(GroundingFailureCode.MISSING_CALL)
        if not self._round_target_seen:
            # Unrelated calls still execute under the normal contract. Repair is
            # scheduled only after their outcomes are appended in model order.
            self.failure_code = GroundingFailureCode.WRONG_CALL
            return self.state
        return self.state

    def finish_tool_round(self) -> GroundingState:
        if self.state is GroundingState.SATISFIED:
            return self.state
        if not self.blocks_output:
            return self.state
        if self._round_invalid:
            return self._repair_or_fail(GroundingFailureCode.INVALID_ARGUMENTS)
        if self._round_failed:
            return self.fail(GroundingFailureCode.TOOL_FAILURE)
        if self._round_target_seen:
            return self.fail(GroundingFailureCode.TOOL_FAILURE)
        return self._repair_or_fail(GroundingFailureCode.WRONG_CALL)

    def fail(self, code: GroundingFailureCode | str) -> GroundingState:
        try:
            self.failure_code = GroundingFailureCode(str(code))
        except ValueError:
            self.failure_code = GroundingFailureCode.INTERNAL
        self.state = GroundingState.FAILED
        return self.state

    def exact_tool_choice(self) -> dict[str, Any] | None:
        if not self.forced:
            return None
        return {"type": "function", "function": {"name": self.preferred_tool}}

    def bounded_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "state": self.state.value,
            "attempt": self.attempt,
            "required": self.required,
            "forced": self.forced,
            "candidates": self.candidate_count,
            "offered": self.offered_count,
            "reason": self.requirement,
        }
        if self.failure_code:
            data["fallback_reason"] = self.failure_code.value
        return data

    def _repair_or_fail(self, code: GroundingFailureCode) -> GroundingState:
        if self.repair_count >= 1:
            return self.fail(code)
        self.repair_count += 1
        self.failure_code = code
        self.state = GroundingState.REPAIR
        self._reset_round()
        return self.state

    def _reset_round(self) -> None:
        self._round_target_seen = False
        self._round_any_call = False
        self._round_invalid = False
        self._round_failed = False
        self._round_names.clear()


__all__ = ["GroundingFailureCode", "GroundingLatch", "GroundingState"]
