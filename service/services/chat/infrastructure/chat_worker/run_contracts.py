"""Private value objects shared by chat worker execution phases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from service.services.chat.infrastructure.chat_worker.phases import RunPhaseState


@dataclass(frozen=True, slots=True)
class WorkerRunRequest:
    job_id: str
    thread_id: str
    text: str
    user_id: str | None
    session_data: dict[str, Any] | None = None
    selected_model: str | None = None
    route_override: str | None = None
    input_type: str | None = None
    web_search: bool = False
    deep_research: bool = False
    file_context: str = ""
    attachments: list[Any] | None = None
    memory_enabled: bool = True
    ldr_model: str | None = None
    ldr_strategy: str | None = None
    multi_intent: bool | None = None
    persona_ids: list[str] | None = None
    planning: bool | None = None
    celery_task_id: str | None = None

    @property
    def run_id(self) -> str:
        return self.celery_task_id or self.job_id

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> WorkerRunRequest:
        """Build from a facade's locals while ignoring non-wire dependencies."""

        return cls(**{name: values[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class WorkerExecutionHooks:
    bind_runtime_settings: Any
    sync_provider_keys: Any
    publisher_factory: Any
    build_file_service: Any
    redelivery_short_circuit: Any
    update_job_status: Any
    restore_history: Any
    reservation_context_chars: Any
    reserve_credits: Any
    recover_attachment_text: Any
    recall_thread_file: Any
    resolve_persona_switched: Any
    run_with_cancel: Any
    reply_or_provider_failure: Any
    record_catalog_events: Any
    charge_and_describe: Any
    persist_chat_turn: Any
    publish_committed_turn: Any
    extract_memory: Any
    handle_failure: Any


@dataclass(slots=True)
class MutableRunState:
    phase: RunPhaseState = field(default_factory=RunPhaseState)
    reservation_id: str | None = None
    reserved_estimate: int = 0
    charged_credits: int = 0
    streamed_parts: list[str] = field(default_factory=list)
    engine_env: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreparedRunContext:
    pseudo_session: Any
    file_context: str
    memory_parts: tuple[str, str]
    history_messages: list[Any]
    compact_summary: str
    persona_switched: bool
    tabular_files: list[Any]
    reference_image_url: str | None
    has_non_tabular_attachment: bool
    repo_graph_ids: list[str]
    attachments: list[dict[str, Any]]
    on_event: Any
    workflow_observations: list[dict[str, Any]]
    workflow_executions: list[dict[str, Any]]


__all__ = [
    "MutableRunState",
    "PreparedRunContext",
    "WorkerExecutionHooks",
    "WorkerRunRequest",
]
