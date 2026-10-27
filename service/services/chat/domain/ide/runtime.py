"""Private runtime identity is separate from public repository identity."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

RuntimeState = Literal[
    "dispatching", "ready", "pending", "unknown", "unavailable", "expired", "rejected"
]
RUNTIME_STATES = frozenset(
    {"dispatching", "ready", "pending", "unknown", "unavailable", "expired", "rejected"}
)


@dataclass(frozen=True, slots=True)
class RepositoryScope:
    thread_id: UUID
    user_id: UUID
    repository_id: UUID

    def params(self) -> dict[str, UUID]:
        return {
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "repository_id": self.repository_id,
        }


@dataclass(frozen=True, slots=True)
class RuntimeAttempt:
    allocation_id: UUID
    expires_at: int
    state: RuntimeState
    observation: int
    retry_allowed: bool = False

    @classmethod
    def from_row(cls, row: Any) -> RuntimeAttempt | None:
        return (
            cls(
                **{
                    key: row[key]
                    for key in (
                        "allocation_id",
                        "expires_at",
                        "state",
                        "observation",
                        "retry_allowed",
                    )
                }
            )
            if row is not None
            else None
        )


@dataclass(frozen=True, slots=True)
class WorkspaceBinding:
    workspace_id: str
    token: str = field(repr=False)
    expires_at: int
    root: str = "/workspace"


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    state: RuntimeState
    binding: WorkspaceBinding | None = field(default=None, repr=False)
    retry_allowed: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedRuntime:
    attempt: RuntimeAttempt
    binding: WorkspaceBinding = field(repr=False)


def generation_tag(attempt: RuntimeAttempt) -> str:
    """Public resource version, not a routable allocation ID or capability."""
    return allocation_generation_tag(attempt.allocation_id)


def allocation_generation_tag(allocation_id: UUID) -> str:
    return hashlib.sha256(b"ide-generation-v1|" + allocation_id.bytes).hexdigest()
