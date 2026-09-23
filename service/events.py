"""Контракт событий агентного стриминга (gpthub_core).

Единственный источник правды для ``AgentEvent``/``EventType`` — того самого потока,
что сайдкар agents будет стримить по HTTP (`/run`, Фаза 4), а backend форвардит в
Redis-стрим и WS. Самодостаточен: только stdlib + pydantic, без ``service.*``.
"""

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

LEGACY_GUARDRIALS_KEY = "guardrials"
GUARDRAILS_KEY = "guardrails"
AUTO_REASON_CODES = frozenset(
    {
        "shortcut_empty",
        "shortcut_smalltalk",
        "shortcut_continue",
        "model_classification",
        "confirmation_required",
        "video_confirmation_required",
        "disabled",
        "explicit_route",
        "explicit_search",
        "nontext_input",
        "multimodal_input",
        "pre_resolved_route",
        "decision_unavailable",
    }
)
_ERROR_FIELDS = frozenset({"failure_code", "category", "retryable", "status_family"})
ERROR_CODES = frozenset(
    {
        "timeout",
        "transport",
        "remote",
        "protocol",
        "conflict",
        "expired",
        "unavailable",
        "invalid",
        "no_compatible_model",
        "cancelled",
        "policy",
        "provider_protocol",
        "tool_schema",
        "tool_choice",
        "tls_config",
        "tls",
        "auth",
        "quota",
        "rate_limit",
        "payload",
        "safety",
        "internal",
    }
)
ERROR_CATEGORIES = frozenset({"provider", "mcp", "workspace", "sidecar", "internal"})
STATUS_FAMILIES = frozenset({"none", "4xx", "5xx", "transport"})
DOCUMENT_STAGES = frozenset(
    {
        "intent",
        "evidence",
        "outline",
        "section_authoring",
        "source_publish",
        "compile",
        "deterministic_audit",
        "visual_audit",
        "delivery",
    }
)
DOCUMENT_STATUSES = frozenset(
    {"running", "ready", "empty", "pending", "queued", "failed", "draft_ready", "deferred"}
)
DOCUMENT_OUTCOMES = frozenset(
    {"awaiting_confirmation", "draft_ready", "completed", "deferred", "failed"}
)
DOCUMENT_FAILURE_CODES = frozenset(
    {
        "draft_protocol",
        "draft_invalid",
        "evidence_incomplete",
        "source_conflict",
        "compile_failed",
        "deterministic_audit_failed",
        "visual_pending",
        "visual_audit_failed",
        "delivery_deferred",
        "selected_model_unavailable",
        "workspace_unavailable",
        "authoring_unsupported",
        "unresolved_requirements",
        "cancelled",
        "internal",
    }
)
DOCUMENT_FACTS = frozenset(
    {
        "attachment_count",
        "material_chunk_count",
        "research_source_count",
        "bibliography_source_count",
        "bibliography_complete",
    }
)


def _sanitize_document_status_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    raw = metadata.get("document_status")
    if not isinstance(raw, dict):
        return {"kind": "document_status"}
    stage = str(raw.get("stage") or "")
    status = str(raw.get("status") or "")
    outcome = str(raw.get("outcome") or metadata.get("document_outcome") or "")
    failure = str(raw.get("failure_code") or metadata.get("document_failure_code") or "")
    facts: dict[str, int | bool] = {}
    for key, value in (raw.get("facts") if isinstance(raw.get("facts"), dict) else {}).items():
        if key in DOCUMENT_FACTS and isinstance(value, (bool, int)):
            facts[key] = value
    body = {
        **({"stage": stage} if stage in DOCUMENT_STAGES else {}),
        **({"status": status} if status in DOCUMENT_STATUSES else {}),
        "retryable": bool(raw.get("retryable", False)),
        **({"outcome": outcome} if outcome in DOCUMENT_OUTCOMES else {}),
        **({"failure_code": failure} if failure in DOCUMENT_FAILURE_CODES else {}),
        **({"facts": facts} if facts else {}),
    }
    return {
        "kind": "document_status",
        "document_status": body,
        **({"document_outcome": outcome} if outcome in DOCUMENT_OUTCOMES else {}),
        **({"document_failure_code": failure} if failure in DOCUMENT_FAILURE_CODES else {}),
    }


def _add_legacy_guardrials_key(metadata: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return metadata
    if GUARDRAILS_KEY not in metadata:
        return metadata
    if LEGACY_GUARDRIALS_KEY in metadata:
        return metadata
    return {
        **metadata,
        LEGACY_GUARDRIALS_KEY: metadata[GUARDRAILS_KEY],
    }


def _sanitize_auto_mode_metadata(metadata: Any) -> Any:
    """Keep auto-mode trace and confirmation metadata bounded across old producers."""
    if not isinstance(metadata, dict):
        return metadata
    if metadata.get("kind") == "document_status":
        return _sanitize_document_status_metadata(metadata)
    sanitized = dict(metadata)
    for key in ("auto", "mode_offer"):
        value = sanitized.get(key)
        if not isinstance(value, dict):
            continue
        cleaned = {
            item_key: item_value
            for item_key, item_value in value.items()
            if item_key not in {"prompt", "reason"}
        }
        code = value.get("reason_code")
        if isinstance(code, str) and code in AUTO_REASON_CODES:
            cleaned["reason_code"] = code
        else:
            cleaned.pop("reason_code", None)
        sanitized[key] = cleaned
    if sanitized.get("kind") == "legacy_route_used":
        sanitized.pop("reason", None)
        code = sanitized.get("reason_code")
        if not isinstance(code, str) or code not in AUTO_REASON_CODES:
            sanitized.pop("reason_code", None)
    return sanitized


def _sanitize_error_metadata(metadata: Any) -> dict[str, Any]:
    value = metadata if isinstance(metadata, dict) else {}
    legacy_policy_block = value.get("guardrail_block") is True
    code = str(value.get("failure_code") or ("policy" if legacy_policy_block else "internal"))
    category = str(value.get("category") or "internal")
    family = str(value.get("status_family") or "none")
    cleaned = {key: value[key] for key in _ERROR_FIELDS if key in value}
    cleaned["failure_code"] = code if code in ERROR_CODES else "internal"
    cleaned["category"] = category if category in ERROR_CATEGORIES else "internal"
    cleaned["retryable"] = bool(value.get("retryable", False))
    cleaned["status_family"] = family if family in STATUS_FAMILIES else "none"
    return cleaned


def _safe_error_data(metadata: Any) -> str:
    cleaned = _sanitize_error_metadata(metadata)
    if cleaned["failure_code"] == "cancelled":
        return "Выполнение отменено."
    if cleaned["retryable"]:
        return "Выполнение временно недоступно; повторите запрос позже."
    return "Выполнение завершилось безопасно обработанной ошибкой."


class EventType(StrEnum):
    """Types of events emitted by agent system."""

    ROUTING_START = "routing_start"
    ROUTING_COMPLETE = "routing_complete"

    AGENT_START = "agent_start"
    AGENT_COMPLETE = "agent_complete"

    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    TOOL_CALL_ERROR = "tool_call_error"

    STREAM_CHUNK = "stream_chunk"
    STREAM_COMPLETE = "stream_complete"

    STRUCTURED_OUTPUT = "structured_output"

    STATUS_UPDATE = "status_update"

    ERROR = "error"


class AgentEvent(BaseModel):
    """Unified event structure for agent system.

    All agents emit these events which are serialized to WebSocket.
    """

    type: EventType = Field(..., description="Event type")
    agent_name: str | None = Field(None, description="Name of the agent emitting this event")
    data: Any = Field(None, description="Event payload (can be string, dict, list, etc)")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")
    seq: int = Field(0, description="Sequence number for ordering")

    @field_validator("metadata", mode="before")
    @classmethod
    def _coerce_none_metadata(cls, value: Any) -> Any:
        # metadata — всегда dict. Явный None (напр. complete_event(msg) без
        # метаданных или _usage_meta(...)→None на путях без usage) должен
        # трактоваться как «нет метаданных», а не падать ValidationError и не
        # ронять весь субагент на его завершающем событии.
        return {} if value is None else value

    @model_validator(mode="after")
    def _bound_error_payload(self):
        if self.type == EventType.ERROR:
            self.data = _safe_error_data(self.metadata)
            self.metadata = _sanitize_error_metadata(self.metadata)
        return self

    @model_serializer(mode="wrap")
    def serialize_with_legacy_guardrials(self, handler):
        payload = handler(self)
        if self.type == EventType.ERROR:
            payload["data"] = _safe_error_data(self.metadata)
            payload["metadata"] = _sanitize_error_metadata(self.metadata)
        payload["metadata"] = _add_legacy_guardrials_key(payload.get("metadata") or {})
        return payload

    model_config = ConfigDict(use_enum_values=True)


class EventSerializer:
    """AgentEvent → JSON-совместимый dict для транспорта (Redis-стрим/WS).

    Утиная типизация события (не импортит ``AgentEvent``), так что переносима: и
    сайдкар (стримит по HTTP), и backend (форвардит в Redis/WS) сериализуют одинаково.
    Сам транспорт (``AgentStreamPublisher`` → Redis) остаётся в backend-инфраструктуре.
    """

    @staticmethod
    def to_jsonable(value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, default=lambda _value: None))
        except Exception:
            return None

    def serialize(self, *, event: Any, job_id: str) -> dict[str, Any]:
        evt_type = event.type.value if hasattr(event.type, "value") else str(event.type)
        is_error = evt_type == EventType.ERROR.value
        event_metadata = (
            _sanitize_error_metadata(event.metadata)
            if is_error
            else _sanitize_auto_mode_metadata(event.metadata or {})
        )
        event_data = _safe_error_data(event.metadata) if is_error else event.data
        payload = {
            "type": evt_type,
            "job_id": job_id,
            "data": self.to_jsonable(event_data),
            "message": self.to_jsonable(event_data),
            "agent_name": event.agent_name,
            "metadata": self.to_jsonable(event_metadata),
            "seq": getattr(event, "seq", 0),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if isinstance(event.metadata, dict) and event.metadata.get("tool_name"):
            payload["tool_name"] = event.metadata.get("tool_name")
        elif evt_type.startswith("tool_call") and isinstance(event.data, str):
            payload["tool_name"] = event.data
        return payload
