"""Versioned private harness state and deterministic public completion projection.

Shared by the sidecar and backend. No network, credentials, prompt formatting or
model calls belong here; only trusted executors may append effect evidence.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TaskKind = Literal["analysis", "change", "document"]
Action = Literal["read", "write", "exec", "document"]
CriterionKind = Literal["read", "file", "command", "pdf"]
CriterionId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]

# Форма relative_target без lookahead, пригодная для JSON-schema grammar.
_PATH_CHAR = r"[^/\\:\x00-\x1f\x7f]"
_PATH_FIRST = r"[^./\\:\x00-\x1f\x7f]"
_PATH_PART = rf"({_PATH_FIRST}{_PATH_CHAR}*|\.{_PATH_FIRST}{_PATH_CHAR}*|\.\.{_PATH_CHAR}+)"
TARGET_PATTERN = rf"^({_PATH_PART}(/{_PATH_PART})*)?$"
NONEMPTY_TARGET_PATTERN = rf"^{_PATH_PART}(/{_PATH_PART})*$"
# Файловый адаптер допускает двоеточие в POSIX-имени; контракт задачи строже.
FILE_PATH_PATTERN = TARGET_PATTERN.replace(":", "")
NONEMPTY_FILE_PATH_PATTERN = NONEMPTY_TARGET_PATTERN.replace(":", "")


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def immutable_items(value):
    return tuple(value) if isinstance(value, list) else value


class TaskCriterion(ContractModel):
    criterion_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: CriterionKind
    target: str = Field(default="", max_length=1024)
    expected_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("target")
    @classmethod
    def relative_target(cls, value: str) -> str:
        if value and (
            "\\" in value
            or ":" in value
            or value.startswith("/")
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("task_target_invalid")
        return value


class TaskContract(ContractModel):
    schema_version: Literal[1] = 1
    task_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    project_id: str = Field(min_length=1, max_length=128)
    generation: str = Field(min_length=1, max_length=128)
    kind: TaskKind
    goal: str = Field(min_length=1, max_length=16000, repr=False)
    actions: tuple[Action, ...] = Field(min_length=1, max_length=4)
    criteria: tuple[TaskCriterion, ...] = Field(min_length=1, max_length=64)
    round_limit: int = Field(default=16, ge=1, le=16)
    repair_limit: int = Field(default=2, ge=0, le=2)
    credit_limit: int = Field(ge=0, le=1_000_000_000)
    active_limit_ms: int = Field(default=570000, ge=1, le=3600000)

    _items = field_validator("actions", "criteria", mode="before")(immutable_items)

    @model_validator(mode="after")
    def coherent(self):
        canonical_uuid(self.task_id)
        ids = [criterion.criterion_id for criterion in self.criteria]
        if len(ids) != len(set(ids)) or len(self.actions) != len(set(self.actions)):
            raise ValueError("task_contract_invalid")
        required = {"read": "read", "file": "write", "command": "exec", "pdf": "document"}
        if any(required[item.kind] not in self.actions for item in self.criteria):
            raise ValueError("task_permission_missing")
        if self.kind == "analysis" and self.actions != ("read",):
            raise ValueError("analysis_must_be_read_only")
        if self.kind == "change" and not any(item.kind == "file" for item in self.criteria):
            raise ValueError("change_requires_file_evidence")
        if self.kind == "document" and not any(item.kind == "pdf" for item in self.criteria):
            raise ValueError("document_requires_artifact")
        return self

    @property
    def digest(self) -> str:
        return digest_payload(self.model_dump(mode="json"))


class TaskEvidence(ContractModel):
    criterion_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    operation_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    kind: CriterionKind
    target: str = Field(default="", max_length=1024)
    source_revision: str = Field(min_length=1, max_length=128)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["passed", "failed", "unknown"]
    exit_code: int | None = None
    artifact_id: str | None = Field(default=None, max_length=128)

    _target = field_validator("target")(TaskCriterion.relative_target.__func__)

    @model_validator(mode="after")
    def proof_fields(self):
        canonical_uuid(self.operation_id)
        if self.outcome == "passed":
            if self.kind == "command" and self.exit_code != 0:
                raise ValueError("command_not_successful")
            if self.kind == "pdf" and not self.artifact_id:
                raise ValueError("artifact_not_confirmed")
        return self


class TaskBudget(ContractModel):
    spent_credits: int = Field(default=0, ge=0, le=1_000_000_000)
    held_credits: int = Field(default=0, ge=0, le=1_000_000_000)
    active_ms: int = Field(default=0, ge=0, le=3600000)


class PlanStep(ContractModel):
    step_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    criterion_ids: tuple[CriterionId, ...] = Field(min_length=1, max_length=64)
    state: Literal["pending", "running", "done", "blocked"] = "pending"

    _items = field_validator("criterion_ids", mode="before")(immutable_items)


class TaskState(ContractModel):
    schema_version: Literal[1] = 1
    contract: TaskContract
    revision: int = Field(default=0, ge=0, le=1_000_000)
    source_revision: str = Field(min_length=1, max_length=128)
    rounds: int = Field(default=0, ge=0, le=16)
    repairs: int = Field(default=0, ge=0, le=2)
    protocol_repairs: int = Field(default=0, ge=0, le=1)
    budget: TaskBudget = Field(default_factory=TaskBudget)
    plan: tuple[PlanStep, ...] = Field(default=(), max_length=64)
    evidence: tuple[TaskEvidence, ...] = Field(default=(), max_length=256)
    cancelled: bool = False

    _items = field_validator("plan", "evidence", mode="before")(immutable_items)

    @model_validator(mode="after")
    def within_contract(self):
        known = {item.criterion_id: item for item in self.contract.criteria}
        if self.rounds > self.contract.round_limit or self.repairs > self.contract.repair_limit:
            raise ValueError("task_limit_exceeded")
        if self.budget.spent_credits + self.budget.held_credits > self.contract.credit_limit:
            raise ValueError("task_credit_limit_exceeded")
        if self.budget.active_ms > self.contract.active_limit_ms:
            raise ValueError("task_deadline_exceeded")
        if len({step.step_id for step in self.plan}) != len(self.plan):
            raise ValueError("task_plan_invalid")
        if any(set(step.criterion_ids) - known.keys() for step in self.plan):
            raise ValueError("task_plan_invalid")
        for item in self.evidence:
            criterion = known.get(item.criterion_id)
            if criterion is None or criterion.kind != item.kind:
                raise ValueError("task_evidence_invalid")
            if criterion.target and criterion.target != item.target:
                raise ValueError("task_evidence_wrong_target")
        receipts = [(item.operation_id, item.criterion_id, item.outcome) for item in self.evidence]
        if len(receipts) != len(set(receipts)):
            raise ValueError("task_evidence_duplicate")
        return self

    def advance(self, **updates) -> TaskState:
        """Every update is revalidated; model_copy(update=...) bypasses validators."""
        raw = {**self.model_dump(mode="json"), **updates, "revision": self.revision + 1}
        return TaskState.model_validate(raw)

    def claim_round(self) -> TaskState:
        if self.cancelled:
            raise ValueError("task_cancelled")
        return self.advance(rounds=self.rounds + 1)


def digest_payload(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def canonical_uuid(value: str) -> str:
    if str(UUID(value)) != value:
        raise ValueError("task_identifier_invalid")
    return value


class CompletionVerifier:
    @staticmethod
    def evaluate(state: TaskState, *, pending_operations: bool = False) -> dict:
        latest = {item.criterion_id: item for item in state.evidence}
        confirmed, unchecked, references = [], [], []
        for criterion in state.contract.criteria:
            item = latest.get(criterion.criterion_id)
            if (
                item
                and item.outcome == "passed"
                and item.source_revision == state.source_revision
                and (criterion.expected_digest is None or item.digest == criterion.expected_digest)
            ):
                confirmed.append(criterion.criterion_id)
                references.append(
                    {
                        "criterion_id": item.criterion_id,
                        "operation_id": item.operation_id,
                        "kind": item.kind,
                        "target": item.target,
                        "digest": item.digest,
                        "artifact_id": item.artifact_id,
                        "source_revision": item.source_revision,
                    }
                )
            else:
                unchecked.append(criterion.criterion_id)
        blocker = "cancelled" if state.cancelled else ""
        if not blocker and state.budget.held_credits:
            blocker = "cost_unknown"
        if not blocker and pending_operations:
            blocker = "operation_unknown"
        if not blocker and unchecked:
            expected = {item.criterion_id: item.expected_digest for item in state.contract.criteria}
            failed = any(
                latest.get(key)
                and (
                    latest[key].outcome == "failed"
                    or (
                        latest[key].source_revision == state.source_revision
                        and expected[key] is not None
                        and latest[key].digest != expected[key]
                    )
                )
                for key in unchecked
            )
            unknown = any(latest.get(key) and latest[key].outcome == "unknown" for key in unchecked)
            blocker = (
                "operation_unknown"
                if unknown
                else ("verification_failed" if failed else "verification_missing")
            )
        if not blocker and any(step.state != "done" for step in state.plan):
            blocker = "plan_incomplete"
        complete = not blocker and not unchecked
        return {
            "schema_version": 2,
            "status": "cancelled" if state.cancelled else ("completed" if complete else "partial"),
            "verified": complete,
            "blocker": blocker or None,
            "confirmed": confirmed,
            "unchecked": unchecked,
            "references": references,
            "rounds": state.rounds,
            "repair_cycles": state.repairs,
        }


class EvidenceReference(ContractModel):
    criterion_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    operation_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    kind: CriterionKind
    target: str = Field(max_length=1024)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_revision: str = Field(min_length=1, max_length=128)
    artifact_id: str | None = Field(default=None, max_length=128)

    _target = field_validator("target")(TaskCriterion.relative_target.__func__)
    _operation = field_validator("operation_id")(canonical_uuid)


class TaskResultV2(ContractModel):
    """Public facts only. Parsing a projection never makes it trusted evidence."""

    schema_version: Literal[2]
    status: Literal["completed", "partial", "blocked", "waiting_user", "cancelled"]
    verified: bool
    blocker: (
        Literal[
            "cancelled",
            "cost_unknown",
            "verification_missing",
            "verification_failed",
            "operation_unknown",
            "plan_incomplete",
            "budget_exhausted",
            "budget_unavailable",
            "checkpoint_unavailable",
            "checkpoint_conflict",
            "provider_state_incompatible",
            "binding_changed",
            "user_decision_required",
            "verification_unavailable",
            "task_contract_invalid",
            "task_permission_denied",
            "dispatch_disabled",
            "harness_fenced",
            "unsupported_adapter",
            "usage_limit_exceeded",
            "operation_conflict",
            "no_progress",
            "prompt_budget",
            "round_limit",
            "unconfirmed_effect",
            "tool_failed",
        ]
        | None
    )
    confirmed: tuple[CriterionId, ...] = Field(max_length=64)
    unchecked: tuple[CriterionId, ...] = Field(max_length=64)
    references: tuple[EvidenceReference, ...] = Field(max_length=64)
    rounds: int = Field(ge=0, le=16)
    repair_cycles: int = Field(ge=0, le=2)

    _items = field_validator("confirmed", "unchecked", "references", mode="before")(immutable_items)

    @model_validator(mode="after")
    def consistent(self):
        complete = self.status == "completed"
        if complete != self.verified or complete != (self.blocker is None):
            raise ValueError("task_result_inconsistent")
        if complete and self.unchecked:
            raise ValueError("task_result_unverified")
        if (self.status == "cancelled") != (self.blocker == "cancelled"):
            raise ValueError("task_result_inconsistent")
        if len(set(self.confirmed + self.unchecked)) != len(self.confirmed + self.unchecked):
            raise ValueError("task_result_duplicate")
        refs = [item.criterion_id for item in self.references]
        if sorted(refs) != sorted(self.confirmed) or not (self.confirmed or self.unchecked):
            raise ValueError("task_result_references_invalid")
        return self
