"""Frozen capture intent and publication outcome, never a Git commit."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.runtime import RepositoryScope

CheckpointState = Literal["pending", "published", "conflict", "retired"]
CHECKPOINT_STATES = frozenset({"pending", "published", "conflict", "retired"})


@dataclass(frozen=True, slots=True)
class CheckpointIntent:
    blob: CheckpointBlob
    allocation_id: UUID = field(repr=False)
    base_checkpoint_id: UUID | None
    storage_namespace: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.blob, CheckpointBlob)
            or not isinstance(self.storage_namespace, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.storage_namespace)
            or not isinstance(self.allocation_id, UUID)
            or self.base_checkpoint_id is not None
            and (
                not isinstance(self.base_checkpoint_id, UUID)
                or self.base_checkpoint_id == self.blob.checkpoint_id
            )
        ):
            raise IdeCheckpointError()

    def params(self) -> dict[str, Any]:
        return {
            **self.blob.scope.params(),
            "checkpoint_id": self.blob.checkpoint_id,
            "allocation_id": self.allocation_id,
            "base_checkpoint_id": self.base_checkpoint_id,
            "sha256": self.blob.sha256,
            "size": self.blob.size,
            "storage_namespace": self.storage_namespace,
        }


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    intent: CheckpointIntent
    state: CheckpointState
    current_checkpoint_id: UUID | None
    upload_settled: bool = False
    collected: bool = False

    @property
    def is_current(self) -> bool:
        return (
            self.state == "published"
            and self.current_checkpoint_id == self.intent.blob.checkpoint_id
        )

    @classmethod
    def from_row(cls, row: Any) -> CheckpointRecord | None:
        if row is None:
            return None
        if row["state"] not in CHECKPOINT_STATES:
            raise IdeCheckpointError()
        scope = RepositoryScope(row["thread_id"], row["user_id"], row["repository_id"])
        return cls(
            CheckpointIntent(
                CheckpointBlob(scope, row["checkpoint_id"], row["sha256"], row["size"]),
                row["allocation_id"],
                row["base_checkpoint_id"],
                row["storage_namespace"],
            ),
            row["state"],
            row["current_checkpoint_id"],
            row.get("upload_settled_at") is not None,
            row.get("collected_at") is not None,
        )


@dataclass(frozen=True, slots=True)
class CheckpointReservation:
    record: CheckpointRecord | None = None
    dispatch: bool = False
    failure: Literal["missing", "runtime_not_ready", "quota", "pending", "head_changed"] | None = (
        None
    )
