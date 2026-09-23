"""Bounded terminal and stage contract for one Document Forge run."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from service.events import AgentEvent, EventType


class DocumentStage(StrEnum):
    INTENT = "intent"
    EVIDENCE = "evidence"
    OUTLINE = "outline"
    SECTION_AUTHORING = "section_authoring"
    SOURCE_PUBLISH = "source_publish"
    COMPILE = "compile"
    DETERMINISTIC_AUDIT = "deterministic_audit"
    VISUAL_AUDIT = "visual_audit"
    DELIVERY = "delivery"


class DocumentRunOutcome(StrEnum):
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    DRAFT_READY = "draft_ready"
    COMPLETED = "completed"
    DEFERRED = "deferred"
    FAILED = "failed"


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


@dataclass(frozen=True, slots=True)
class DocumentStatus:
    stage: DocumentStage
    status: str
    outcome: DocumentRunOutcome | None = None
    failure_code: str | None = None
    retryable: bool = False
    facts: dict[str, int | bool] | None = None

    def metadata(self) -> dict[str, Any]:
        code = self.failure_code if self.failure_code in DOCUMENT_FAILURE_CODES else None
        return {
            "kind": "document_status",
            "document_status": {
                "stage": self.stage.value,
                "status": str(self.status)[:32],
                "retryable": bool(self.retryable),
                **({"failure_code": code} if code else {}),
                **({"outcome": self.outcome.value} if self.outcome else {}),
                **({"facts": dict(self.facts)} if self.facts else {}),
            },
            **({"document_outcome": self.outcome.value} if self.outcome else {}),
            **({"document_failure_code": code} if code else {}),
        }


def document_status_event(
    agent_name: str,
    stage: DocumentStage,
    status: str,
    *,
    outcome: DocumentRunOutcome | None = None,
    failure_code: str | None = None,
    retryable: bool = False,
    facts: dict[str, int | bool] | None = None,
) -> AgentEvent:
    value = DocumentStatus(stage, status, outcome, failure_code, retryable, facts)
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name=agent_name,
        data="Состояние PDF-документа обновлено",
        metadata=value.metadata(),
    )


__all__ = [
    "DOCUMENT_FAILURE_CODES",
    "DocumentRunOutcome",
    "DocumentStage",
    "DocumentStatus",
    "document_status_event",
]
