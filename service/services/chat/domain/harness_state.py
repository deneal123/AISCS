"""Private checkpoint transitions. No model, transport or billing authority here."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from service.shared.task_contract import (
    Action,
    ContractModel,
    CriterionId,
    TaskEvidence,
    TaskState,
    canonical_uuid,
    digest_payload,
    immutable_items,
)


class ProviderBinding(ContractModel):
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    model: str = Field(min_length=1, max_length=256)
    state_id: str | None = Field(default=None, max_length=2048, repr=False)


class HarnessCheckpoint(ContractModel):
    state: TaskState
    provider: ProviderBinding | None = Field(default=None, repr=False)

    @property
    def digest(self) -> str:
        return digest_payload(self.model_dump(mode="json"))


class OperationIntent(ContractModel):
    operation_id: str
    kind: Literal["tool", "command", "build", "provider"]
    action: Action
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_./-]{0,127}$")
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_revision: str = Field(min_length=1, max_length=128)
    criterion_ids: tuple[CriterionId, ...] = Field(default=(), max_length=64)

    _operation = field_validator("operation_id")(canonical_uuid)
    _items = field_validator("criterion_ids", mode="before")(immutable_items)

    @model_validator(mode="after")
    def unique_criteria(self):
        if len(set(self.criterion_ids)) != len(self.criterion_ids):
            raise ValueError("operation_criteria_invalid")
        required = {"command": "exec", "build": "document", "provider": "read"}.get(self.kind)
        if required is not None and self.action != required:
            raise ValueError("operation_action_invalid")
        if self.kind == "tool" and self.action not in {"read", "write"}:
            raise ValueError("operation_action_invalid")
        return self

    @property
    def digest(self) -> str:
        return digest_payload(self.model_dump(mode="json"))


class OperationReceipt(ContractModel):
    status: Literal["succeeded", "failed", "unknown"]
    result_revision: str | None = Field(default=None, min_length=1, max_length=128)
    result_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    evidence: tuple[TaskEvidence, ...] = Field(default=(), max_length=64)
    diagnostic_ref: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,128}$", repr=False)

    _items = field_validator("evidence", mode="before")(immutable_items)

    @model_validator(mode="after")
    def coherent(self):
        expected = {"succeeded": "passed", "failed": "failed", "unknown": "unknown"}[self.status]
        if any(item.outcome != expected for item in self.evidence):
            raise ValueError("operation_evidence_invalid")
        if len({item.criterion_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("operation_evidence_duplicate")
        return self


def valid_checkpoint_transition(old: HarnessCheckpoint, new: HarnessCheckpoint) -> bool:
    """Only append facts and consume limits; never reset a resumed task."""
    before, after = old.state, new.state
    if before.contract.digest != after.contract.digest or after.revision != before.revision + 1:
        return False
    if before.cancelled and not after.cancelled:
        return False
    if any(
        getattr(after, key) < getattr(before, key)
        for key in ("rounds", "repairs", "protocol_repairs")
    ):
        return False
    if after.budget.spent_credits < before.budget.spent_credits:
        return False
    if after.budget.active_ms < before.budget.active_ms:
        return False
    # Held cost may only be settled by the budget/usage authority, not a checkpoint.
    if after.budget.held_credits != before.budget.held_credits:
        return False
    if after.evidence[: len(before.evidence)] != before.evidence:
        return False
    if old.provider and (
        new.provider is None
        or (new.provider.provider, new.provider.model)
        != (old.provider.provider, old.provider.model)
    ):
        return False
    return True


def receipt_matches(intent: OperationIntent, receipt: OperationReceipt, state: TaskState) -> bool:
    known = {criterion.criterion_id: criterion for criterion in state.contract.criteria}
    actions = {"read": "read", "file": "write", "command": "exec", "pdf": "document"}
    for evidence in receipt.evidence:
        criterion = known.get(evidence.criterion_id)
        if (
            criterion is None
            or evidence.criterion_id not in intent.criterion_ids
            or evidence.operation_id != intent.operation_id
            or evidence.source_revision != (receipt.result_revision or intent.source_revision)
            or evidence.kind != criterion.kind
            or intent.action != actions[evidence.kind]
            or (criterion.target and criterion.target != evidence.target)
        ):
            return False
    return True
