"""Run-scoped execution state shared by orchestration, providers, and tools.

The HTTP request DTO deliberately remains a compatibility contract.  This module is the
internal boundary after parsing: prompt-safe conversation data, policy decisions, private
capabilities, accounting, and mutable execution state no longer have to live in one
Pydantic object that can be serialized accidentally.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from service.domain.capabilities.catalog import RunCapabilitySnapshot
from service.domain.client.protocol import ProviderRunSession
from service.domain.execution.artifacts import WorkflowArtifactStore
from service.domain.execution.grounding import GroundingLatch
from service.domain.execution.progress import TaskProgress
from service.domain.execution.questions import HumanQuestionSession
from service.domain.usage.ledger import UsageLedger, UsageReceipt
from service.shared.task_contract import CompletionVerifier, TaskContract, TaskState

if TYPE_CHECKING:
    from service.domain.client.providers.management.admission import (
        RunProviderAdmission,
        RunProviderSnapshot,
    )


class GroundingRequirement(StrEnum):
    NONE = ""
    WORKSPACE_EXPLICIT = "workspace_explicit"
    WORKSPACE_SOURCE_ONLY = "workspace_source_only"
    FRESH_DATA = "fresh_data"
    TABULAR_SOURCE_ONLY = "tabular_source_only"


# Compatibility name for the S24 development slice.  The state is a requirement,
# not free-form model rationale; new code should use GroundingRequirement.
GroundingReason = GroundingRequirement


class RunExecutionContextError(RuntimeError):
    """Bounded failure raised when production work has no owning run."""

    code = "missing_context"

    def __init__(self) -> None:
        super().__init__(self.code)


def _default_capability_snapshot() -> RunCapabilitySnapshot:
    # Local imports keep the static compiler independent from the MCP adapter while the
    # request entry point can still freeze the already-discovered overlay for this run.
    from service.domain.capabilities.runtime import build_run_capability_snapshot
    from service.infrastructure.mcp.runtime import current_specs

    return build_run_capability_snapshot(current_specs())


@dataclass(slots=True)
class RunPolicyState:
    """Mutable policy output; only bounded values belong here."""

    flags: dict[str, bool] = field(default_factory=dict)
    values: dict[str, str] = field(default_factory=dict)
    grounding_reason: GroundingRequirement = GroundingRequirement.NONE

    def set_flag(self, name: str, value: bool) -> None:
        self.flags[str(name)] = bool(value)

    def flag(self, name: str, default: bool = False) -> bool:
        return bool(self.flags.get(str(name), default))

    def set_value(self, name: str, value: str | None) -> None:
        key = str(name)
        if value:
            self.values[key] = str(value)
        else:
            self.values.pop(key, None)


@dataclass(frozen=True, slots=True)
class PrivateRunResources:
    """Capabilities injected by backend and never intended for prompts or trace."""

    workspace_ref: dict[str, Any] | None = None
    tabular_files: tuple[dict[str, Any], ...] = ()
    reference_image_url: str | None = None
    repo_graph_ids: tuple[str, ...] = ()

    @classmethod
    def from_request(
        cls,
        *,
        workspace_ref: dict[str, Any] | None = None,
        tabular_files: list[dict] | None = None,
        reference_image_url: str | None = None,
        repo_graph_ids: list[str] | None = None,
    ) -> PrivateRunResources:
        return cls(
            workspace_ref=dict(workspace_ref) if isinstance(workspace_ref, dict) else None,
            tabular_files=tuple(
                dict(item) for item in (tabular_files or ()) if isinstance(item, dict)
            ),
            reference_image_url=str(reference_image_url) if reference_image_url else None,
            repo_graph_ids=tuple(str(item) for item in (repo_graph_ids or ()) if item),
        )


@dataclass(slots=True)
class WorkspaceSession:
    """Last revision observed by this run and the mutation serialization lock."""

    revision: str | None = None
    valid: bool = False
    requires_read: bool = False
    mutation_lock: Any = None
    # Run-private IDE read bases and confirmed writes. Never prompt/trace/session
    # metadata: source bytes and authority stay separate from model arguments.
    ide_reads: dict[str, Any] = field(default_factory=dict, repr=False)
    ide_trees: dict[str, Any] = field(default_factory=dict, repr=False)
    ide_writes: dict[str, str | None] = field(default_factory=dict, repr=False)
    ide_unconfirmed: bool = False
    document_unconfirmed: bool = False
    # Only this bounded plain-text projection may enter public result metadata.
    ide_summary: str | None = field(default=None, repr=False)

    @property
    def unconfirmed(self) -> bool:
        return self.ide_unconfirmed or self.document_unconfirmed

    def lock(self):
        if self.mutation_lock is None:
            import asyncio

            self.mutation_lock = asyncio.Lock()
        return self.mutation_lock

    def observe(self, revision: Any) -> str | None:
        value = str(revision or "").strip()
        if value:
            self.revision = value
            self.valid = True
            self.requires_read = False
            return value
        return None

    def invalidate(self, *, require_read: bool = False) -> None:
        self.revision = None
        self.valid = False
        self.requires_read = bool(require_read)


@dataclass(slots=True)
class RunExecutionContext:
    """Single mutable owner for one agents run."""

    resources: PrivateRunResources = field(default_factory=PrivateRunResources)
    usage: UsageLedger = field(default_factory=UsageLedger)
    capabilities: RunCapabilitySnapshot = field(default_factory=_default_capability_snapshot)
    policy: RunPolicyState = field(default_factory=RunPolicyState)
    workspace: WorkspaceSession = field(default_factory=WorkspaceSession)
    question: HumanQuestionSession = field(default_factory=HumanQuestionSession)
    grounding: GroundingLatch = field(default_factory=GroundingLatch)
    task: TaskProgress = field(default_factory=TaskProgress)
    task_state: TaskState | None = field(default=None, repr=False)
    harness: Any = field(default=None, repr=False)
    completion_verifier: CompletionVerifier = field(default_factory=CompletionVerifier, repr=False)
    artifacts: WorkflowArtifactStore = field(default_factory=WorkflowArtifactStore)
    provider_session: ProviderRunSession = field(init=False)
    provider_admission: RunProviderAdmission | None = None
    tool_cache: Any = None
    run_deadline: Any = None
    cancelled: bool = False
    _closed: bool = False
    _response_providers: dict[int, tuple[str, str]] = field(default_factory=dict)
    _response_receipts: dict[int, tuple[Any, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.provider_session = ProviderRunSession(usage=self.usage)
        if self.run_deadline is None:
            from service.shared import deadline

            self.run_deadline = deadline.current()

    @property
    def task_contract(self) -> TaskContract | None:
        return self.task_state.contract if self.task_state is not None else None

    def bind_task_state(self, state: TaskState) -> None:
        """Install a trusted backend checkpoint, never a model-proposed contract."""
        if self.task_state is not None:
            raise RuntimeError("task_already_bound")
        self.task_state = state
        self.task.active = True
        self.task.rounds = state.rounds
        self.task.repairs = state.repairs

    def claim_task_round(self, *, limit: int | None) -> bool:
        state = self.task_state
        if state is not None:
            if state.cancelled or self.cancelled:
                self.task.stop_reason = "cancelled"
                return False
            if state.rounds >= state.contract.round_limit:
                self.task.stop_reason = "round_limit"
                return False
        if not self.task.claim_round(limit=limit):
            return False
        if state is not None:
            self.task_state = state.claim_round()
        return True

    def register_response_provider(self, response: Any, provider: str, model: str) -> None:
        self._response_providers[id(response)] = (str(provider), str(model))

    @property
    def provider_snapshot(self) -> RunProviderSnapshot | None:
        """Immutable model/capability evidence captured at the run boundary."""

        return self.provider_admission.snapshot if self.provider_admission is not None else None

    def claim_response_provider(self, response: Any) -> tuple[str | None, str | None]:
        value = self._response_providers.pop(id(response), None)
        return value if value is not None else (None, None)

    def register_response_receipt(self, response: Any, receipt_id: str) -> None:
        # Retain the object for the bounded lifetime of the run. Mapping only by
        # id(response) lets CPython reuse an id after collection and incorrectly
        # projects an earlier receipt onto a later provider response.
        self._response_receipts[id(response)] = (response, str(receipt_id))

    def response_receipt(self, response: Any) -> UsageReceipt | None:
        entry = self._response_receipts.get(id(response))
        if entry is None or entry[0] is not response:
            return None
        return self.usage.get(entry[1])

    def cancel(self) -> None:
        self.cancelled = True

    def close(self) -> None:
        """Release run-owned provider generations exactly once."""

        if self._closed:
            return
        self._closed = True
        self.artifacts.clear()
        if self.provider_admission is not None:
            self.provider_admission.snapshot.release()


_CURRENT: ContextVar[RunExecutionContext | None] = ContextVar(
    "gpthub_run_execution_context", default=None
)
_USAGE_OBSERVER: ContextVar[Callable[[UsageLedger], None] | None] = ContextVar(
    "gpthub_run_usage_observer", default=None
)


@contextmanager
def observe_run_usage(observer: Callable[[UsageLedger], None]) -> Iterator[None]:
    """Let a transport retain the sole ledger, never the private run resources."""
    token = _USAGE_OBSERVER.set(observer)
    try:
        yield
    finally:
        _USAGE_OBSERVER.reset(token)


def current_execution() -> RunExecutionContext | None:
    return _CURRENT.get()


def require_execution(
    execution: RunExecutionContext | None = None,
) -> RunExecutionContext:
    """Return the single run owner or fail without creating detached state.

    Explicit injection is preferred.  The ContextVar lookup is retained for framework
    callbacks whose signature is controlled by the Agents SDK; it is never a factory.
    """

    resolved = execution or current_execution()
    if resolved is None:
        raise RunExecutionContextError()
    return resolved


def require_current_execution() -> RunExecutionContext:
    """Resolve framework callback state without acting as a context factory."""

    return require_execution()


@contextmanager
def use_run_execution(resources: PrivateRunResources) -> Iterator[RunExecutionContext]:
    execution = RunExecutionContext(resources=resources)
    token = _CURRENT.set(execution)
    try:
        if observer := _USAGE_OBSERVER.get():
            observer(execution.usage)
        yield execution
    finally:
        try:
            execution.close()
        finally:
            _CURRENT.reset(token)


def policy_flag(context: Any, name: str, default: bool = False) -> bool:
    execution = current_execution()
    if execution is not None and name in execution.policy.flags:
        return execution.policy.flag(name, default)
    return bool(getattr(context, name, default)) if context is not None else bool(default)


def set_policy_flag(context: Any, name: str, value: bool) -> None:
    execution = current_execution()
    if execution is not None:
        execution.policy.set_flag(name, value)
        return
    if context is not None:
        setattr(context, name, bool(value))


def set_policy_value(context: Any, name: str, value: str | None) -> None:
    execution = current_execution()
    if execution is not None:
        execution.policy.set_value(name, value)
        return
    if context is not None:
        setattr(context, name, value)


_PRIVATE_CONTEXT_FIELDS = frozenset(
    {
        "workspace_ref",
        "tabular_files",
        "reference_image_url",
    }
)


def prompt_safe_context_payload(context: Any | None) -> dict[str, Any]:
    """Serialize context for internal prompt/tool preparation without capabilities."""

    if context is None:
        return {}
    try:
        if hasattr(context, "model_dump"):
            payload = context.model_dump()
        elif hasattr(context, "dict"):
            payload = context.dict()
        elif isinstance(context, dict):
            payload = dict(context)
        else:
            payload = {}
    except Exception:
        payload = {"user_id": str(getattr(context, "user_id", ""))}
    for key in _PRIVATE_CONTEXT_FIELDS:
        payload.pop(key, None)
    return payload


def tool_context_payload(context: Any | None, tool_name: str | None = None) -> dict[str, Any]:
    """Project only capabilities required by a tool family.

    A missing ``tool_name`` is the SDK compatibility projection.  The custom tool runtime
    always supplies the exact name and therefore receives the narrow projection.
    """

    payload = prompt_safe_context_payload(context)
    execution = current_execution()
    if execution is None:
        # Direct unit callers do not establish run state; retain their old behavior.
        for key in _PRIVATE_CONTEXT_FIELDS:
            value = getattr(context, key, None) if context is not None else None
            if value:
                payload[key] = value
        return payload

    resources = execution.resources
    name = str(tool_name or "")
    compatibility = not name
    if compatibility or name.startswith(("ws_", "tex_", "ide_")):
        if resources.workspace_ref:
            payload["workspace_ref"] = dict(resources.workspace_ref)
            payload["workspace_ref"].pop("harness_ref", None)
    if compatibility or name == "analyze_data":
        if resources.tabular_files:
            payload["tabular_files"] = [dict(item) for item in resources.tabular_files]
    if compatibility or name == "search_knowledge_graph":
        if resources.repo_graph_ids:
            payload["repo_graph_ids"] = list(resources.repo_graph_ids)
    if compatibility and resources.reference_image_url:
        payload["reference_image_url"] = resources.reference_image_url
    return payload


__all__ = [
    "GroundingRequirement",
    "GroundingReason",
    "PrivateRunResources",
    "RunExecutionContext",
    "RunExecutionContextError",
    "RunPolicyState",
    "WorkspaceSession",
    "current_execution",
    "policy_flag",
    "prompt_safe_context_payload",
    "require_current_execution",
    "require_execution",
    "set_policy_flag",
    "set_policy_value",
    "tool_context_payload",
    "use_run_execution",
]
