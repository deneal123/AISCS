"""Private acknowledged harness wire codec. Never a prompt or public trace DTO."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field, field_validator, model_validator

from service.shared.harness_refinement import RefinementAttempt
from service.shared.task_contract import (
    Action,
    ContractModel,
    TaskCriterion,
    TaskEvidence,
    TaskState,
    canonical_uuid,
    digest_payload,
    immutable_items,
)


class HarnessFailure(RuntimeError):
    def __init__(self, code: str = "checkpoint_unavailable"):
        self.code = code
        super().__init__(code)


class Admission(ContractModel):
    task_id: str
    project_id: str = Field(min_length=1, max_length=128)
    generation: str = Field(min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=128, repr=False)
    surface: Literal["ide", "pdf"]
    goal: str = Field(min_length=1, max_length=16000, repr=False)
    source_revision: str = Field(min_length=1, max_length=128)
    actions: tuple[Action, ...] = Field(min_length=1, max_length=4)
    credit_limit: int = Field(ge=0, le=1_000_000_000)
    reservation_id: str
    pricing_model: str | None = Field(default=None, max_length=256)
    prompt_limit: int = Field(default=32768, ge=1, le=262144)
    completion_limit: int = Field(default=4096, ge=1, le=32768)
    paid_call_limit: int = Field(default=48, ge=1, le=128)
    active_limit_ms: int = Field(default=570000, ge=1, le=3600000)

    _ids = field_validator("task_id", "reservation_id")(canonical_uuid)
    _items = field_validator("actions", mode="before")(immutable_items)


class ProviderBinding(ContractModel):
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    model: str = Field(min_length=1, max_length=256)
    state_id: str | None = Field(default=None, max_length=2048, repr=False)


class ToolInvocation(ContractModel):
    id: str = Field(min_length=1, max_length=256)
    type: Literal["function"] = "function"
    function: dict = Field(repr=False)

    @model_validator(mode="after")
    def closed_function(self):
        if set(self.function) != {"name", "arguments"}:
            raise ValueError("transcript_invalid")
        if (
            not isinstance(self.function["name"], str)
            or not 0 < len(self.function["name"]) <= 256
            or not isinstance(self.function["arguments"], str)
            or len(self.function["arguments"]) > 65536
        ):
            raise ValueError("transcript_invalid")
        return self


class TranscriptMessage(ContractModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = Field(default=None, max_length=262144, repr=False)
    tool_call_id: str | None = Field(default=None, max_length=256)
    tool_calls: tuple[ToolInvocation, ...] = Field(default=(), max_length=64, repr=False)

    _items = field_validator("tool_calls", mode="before")(immutable_items)


class Continuation(ContractModel):
    refinement: RefinementAttempt | None = Field(default=None, repr=False)
    messages: tuple[TranscriptMessage, ...] = Field(default=(), max_length=512, repr=False)
    provider: ProviderBinding | None = Field(default=None, repr=False)
    agent_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    next_step: int = Field(default=0, ge=0, le=1024)
    length_continuations: int = Field(default=0, ge=0, le=16)
    call_payload_version: Literal[0, 1, 2] = 0
    admission_active_ms: int = Field(default=0, ge=0, le=3600000)
    clarification: str | None = Field(default=None, max_length=8192, repr=False)
    phase: Literal["admitting", "model", "tools", "final", "waiting_user"] = "admitting"

    _items = field_validator("messages", mode="before")(immutable_items)

    @model_validator(mode="after")
    def canonical(self):
        pending: set[str] = set()
        seen: set[str] = set()
        for message in self.messages:
            if message.role == "tool":
                if message.tool_call_id not in pending or message.tool_calls:
                    raise ValueError("transcript_invalid")
                pending.remove(message.tool_call_id)
            elif pending:
                raise ValueError("transcript_invalid")
            elif message.tool_call_id is not None:
                raise ValueError("transcript_invalid")
            if message.tool_calls:
                if message.role != "assistant":
                    raise ValueError("transcript_invalid")
                for call in message.tool_calls:
                    if call.id in seen:
                        raise ValueError("transcript_invalid")
                    pending.add(call.id)
                    seen.add(call.id)
        if pending and self.phase != "tools":
            raise ValueError("transcript_invalid")
        if len(self.model_dump_json().encode()) > 1048576:
            raise ValueError("checkpoint_too_large")
        return self

    def conversation(self) -> list[dict]:
        result = []
        for message in self.messages:
            raw = message.model_dump(mode="json", exclude_none=True)
            if not raw.get("tool_calls"):
                raw.pop("tool_calls", None)
            result.append(raw)
        return result


class UsageFact(ContractModel):
    receipt_id: str
    provider: str
    model: str
    prompt: int = Field(ge=0)
    completion: int = Field(ge=0)
    kind: str

    _id = field_validator("receipt_id")(canonical_uuid)


class Snapshot(ContractModel):
    admission: Admission = Field(repr=False)
    revision: int = Field(default=0, ge=0, le=1000000)
    state: TaskState | None = Field(default=None, repr=False)
    continuation: Continuation = Field(default_factory=Continuation, repr=False)
    spent_credits: int = Field(default=0, ge=0)
    held_credits: int = Field(default=0, ge=0)
    stopped: bool = False
    settled_credits: int = Field(default=0, ge=0)
    usage: tuple[UsageFact, ...] = Field(default=(), max_length=128)

    _items = field_validator("usage", mode="before")(immutable_items)

    @model_validator(mode="after")
    def consistent(self):
        if self.spent_credits + self.held_credits > self.admission.credit_limit:
            raise ValueError("task_credit_limit_exceeded")
        if self.state is not None:
            contract = self.state.contract
            if (
                contract.task_id != self.admission.task_id
                or contract.project_id != self.admission.project_id
                or contract.generation != self.admission.generation
                or contract.goal != self.admission.goal
                or contract.credit_limit != self.admission.credit_limit
                or set(contract.actions) - set(self.admission.actions)
            ):
                raise ValueError("task_contract_invalid")
        return self

    @property
    def digest(self) -> str:
        return digest_payload(self.model_dump(mode="json"))


class ContractProposal(ContractModel):
    kind: Literal["analysis", "change", "document"]
    criteria: tuple[TaskCriterion, ...] = Field(min_length=1, max_length=62)
    needs_clarification: bool = False
    question: str = Field(default="", max_length=1000)

    _items = field_validator("criteria", mode="before")(immutable_items)


class PaidCall(ContractModel):
    operation_id: str
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    model: str = Field(min_length=1, max_length=256)
    prompt: int = Field(ge=0, le=262144)
    completion: int = Field(ge=0, le=32768)
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: str = Field(default="chat", pattern=r"^[a-z_]{1,64}$")
    billing_tool: Literal["workspace_tool"] | None = None
    continuation_step: int | None = Field(default=None, ge=0, le=1024)
    canonical_request: str | None = Field(default=None, max_length=262144, repr=False)

    _id = field_validator("operation_id")(canonical_uuid)


class CallReceipt(ContractModel):
    operation_id: str
    status: Literal["succeeded", "unknown", "waived"]
    prompt: int = Field(default=0, ge=0, le=262144)
    completion: int = Field(default=0, ge=0, le=32768)
    estimated: bool = False
    message: TranscriptMessage | None = Field(default=None, repr=False)
    finish_reason: (
        Literal["stop", "length", "tool_calls", "function_call", "content_filter"] | None
    ) = None
    provider_state: ProviderBinding | None = Field(default=None, repr=False)

    _id = field_validator("operation_id")(canonical_uuid)


class EffectIntent(ContractModel):
    operation_id: str
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")
    arguments: str = Field(max_length=65536, repr=False)
    action: Action
    source_revision: str = Field(min_length=1, max_length=128)

    _id = field_validator("operation_id")(canonical_uuid)


class EffectResult(ContractModel):
    operation_id: str
    status: Literal["succeeded", "failed", "unknown"]
    text: str = Field(max_length=65536, repr=False)
    evidence: tuple[TaskEvidence, ...] = Field(default=(), max_length=64, repr=False)
    charged: bool | None = None

    _id = field_validator("operation_id")(canonical_uuid)
    _items = field_validator("evidence", mode="before")(immutable_items)

    @model_validator(mode="after")
    def known_charge(self):
        if self.status == "unknown" and self.charged is not None:
            raise ValueError("effect_charge_unknown")
        if self.status == "failed" and self.charged is True:
            raise ValueError("failed_effect_not_billable")
        return self


class OperationStatus(ContractModel):
    """Private read-only journal projection, never a dispatch authorization."""

    operation_id: str
    operation_kind: Literal["paid", "effect"]
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal[
        "allocated", "prepared", "dispatched", "succeeded", "failed", "unknown", "waived"
    ]
    receipt: CallReceipt | EffectResult | None = Field(default=None, repr=False)

    _id = field_validator("operation_id")(canonical_uuid)

    @model_validator(mode="after")
    def coherent(self):
        paid = self.operation_kind == "paid"
        if self.status in ({"prepared", "failed"} if paid else {"allocated", "waived"}):
            raise ValueError("operation_status_invalid")
        if self.receipt is not None:
            if isinstance(self.receipt, CallReceipt) != paid:
                raise ValueError("operation_receipt_invalid")
            if self.receipt.operation_id != self.operation_id:
                raise ValueError("operation_receipt_invalid")
            actual = self.receipt.status
            if paid and self.receipt.estimated:
                actual = "unknown"
            if actual != self.status:
                raise ValueError("operation_receipt_invalid")
        elif self.status in {"succeeded", "failed"}:
            raise ValueError("operation_receipt_missing")
        return self


class Exchange(ContractModel):
    opcode: Literal[
        "state",
        "seal",
        "checkpoint",
        "grant",
        "dispatch",
        "call_receipt",
        "result",
        "prepare_effect",
        "dispatch_effect",
        "effect_receipt",
        "operation_status",
        "lessons",
    ]
    expected_revision: int | None = Field(default=None, ge=0)
    proposal: ContractProposal | None = None
    continuation: Continuation | None = Field(default=None, repr=False)
    state: TaskState | None = Field(default=None, repr=False)
    call: PaidCall | None = None
    receipt: CallReceipt | None = None
    operation_id: str | None = None
    operation_kind: Literal["paid", "effect"] | None = None
    effect: EffectIntent | None = Field(default=None, repr=False)
    effect_result: EffectResult | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def closed_opcode(self):
        required = {
            "state": set(),
            "result": set(),
            "seal": {"proposal", "expected_revision"},
            "checkpoint": {"continuation", "expected_revision"},
            "grant": {"call"},
            "dispatch": {"operation_id"},
            "call_receipt": {"receipt"},
            "prepare_effect": {"effect"},
            "dispatch_effect": {"operation_id"},
            "effect_receipt": {"effect_result"},
            "operation_status": {"operation_id", "operation_kind"},
            "lessons": set(),
        }[self.opcode]
        supplied = {
            key for key, value in self.model_dump().items() if key != "opcode" and value is not None
        }
        allowed = required | ({"state"} if self.opcode == "checkpoint" else set())
        if not required <= supplied or supplied - allowed:
            raise ValueError("harness_request_invalid")
        if self.operation_id is not None:
            canonical_uuid(self.operation_id)
        return self


def canonical_request(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
