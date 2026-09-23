"""Deterministic lifecycle for one durable chat-worker execution.

The state is deliberately process-local.  PostgreSQL job status and the billing
idempotency key remain the durable recovery contract; this latch makes the
ordering of those side effects explicit and testable inside one delivery.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RunPhase(StrEnum):
    RESERVED = "reserved"
    EXECUTING = "executing"
    RESULT_LATCHED = "result_latched"
    CHARGED = "charged"
    PERSISTED = "persisted"
    PUBLISHED = "published"
    FINALIZED = "finalized"


_ORDER = tuple(RunPhase)


class RunPhaseViolation(RuntimeError):
    """Raised when worker orchestration attempts an unsafe phase transition."""


@dataclass(slots=True)
class RunPhaseState:
    """Strict single-delivery phase latch.

    ``published`` means the bounded publication stage was processed.  Redis
    delivery is best-effort after the PostgreSQL success commit, so its boolean
    transport result is retained separately from the phase itself.
    """

    phase: RunPhase | None = None
    publication_delivered: bool | None = None

    def advance(self, target: RunPhase) -> None:
        current_index = -1 if self.phase is None else _ORDER.index(self.phase)
        expected_index = current_index + 1
        if expected_index >= len(_ORDER) or _ORDER[expected_index] is not target:
            raise RunPhaseViolation("invalid_worker_phase_transition")
        self.phase = target

    def mark_publication(self, delivered: bool) -> None:
        self.advance(RunPhase.PUBLISHED)
        self.publication_delivered = bool(delivered)

    @property
    def finalized(self) -> bool:
        return self.phase is RunPhase.FINALIZED


__all__ = ["RunPhase", "RunPhaseState", "RunPhaseViolation"]
