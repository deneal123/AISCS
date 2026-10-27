"""Frozen restore identity; private allocation is not the live repository yet."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.runtime import RepositoryScope, RuntimeAttempt

RestoreState = Literal["pending", "published", "expired", "conflict"]


@dataclass(frozen=True, slots=True)
class RestoreRecord:
    restore_id: UUID
    blob: CheckpointBlob
    base_allocation_id: UUID = field(repr=False)
    allocation_id: UUID = field(repr=False)
    expires_at: int
    storage_namespace: str = field(repr=False)
    state: RestoreState

    def __post_init__(self) -> None:
        if (
            not all(
                isinstance(value, UUID)
                for value in (self.restore_id, self.base_allocation_id, self.allocation_id)
            )
            or self.allocation_id == self.base_allocation_id
            or type(self.expires_at) is not int
            or self.expires_at <= 0
            or not isinstance(self.blob, CheckpointBlob)
            or not 0 < self.blob.size < 2**31
            or not isinstance(self.storage_namespace, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.storage_namespace)
            or self.state not in {"pending", "published", "expired", "conflict"}
        ):
            raise IdeCheckpointError()

    def matches(self, checkpoint_id: UUID, base_allocation_id: UUID) -> bool:
        return (
            self.blob.checkpoint_id == checkpoint_id
            and self.base_allocation_id == base_allocation_id
        )

    def attempt(self, *, dispatch: bool = False) -> RuntimeAttempt:
        # Dispatch is a transaction result, never inferred from a pending row.
        if dispatch and self.state != "pending":
            raise IdeCheckpointError("ide_checkpoint_runtime_not_ready")
        return RuntimeAttempt(
            self.allocation_id, self.expires_at, "dispatching" if dispatch else "unknown", 0
        )

    @classmethod
    def from_row(cls, row: Any) -> RestoreRecord | None:
        if row is None:
            return None
        return cls(
            row["restore_id"],
            CheckpointBlob(
                RepositoryScope(row["thread_id"], row["user_id"], row["repository_id"]),
                row["checkpoint_id"],
                row["sha256"],
                row["size"],
            ),
            row["base_allocation_id"],
            row["allocation_id"],
            row["expires_at"],
            row["storage_namespace"],
            row["state"],
        )


@dataclass(frozen=True, slots=True)
class RestoreReservation:
    record: RestoreRecord | None = None
    dispatch: bool = False
    failure: (
        Literal[
            "missing",
            "checkpoint_not_published",
            "runtime_not_expired",
            "restore_pending",
            "command_busy",
        ]
        | None
    ) = None
