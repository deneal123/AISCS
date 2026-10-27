"""Private immutable blob identity, not a published repository head or backup."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from uuid import UUID

from service.services.chat.domain.ide.runtime import RepositoryScope


class IdeCheckpointError(RuntimeError):
    def __init__(self, code: str = "ide_checkpoint_invalid") -> None:
        self.code = (
            code
            if code
            in {
                "ide_command_busy",
                "ide_checkpoint_invalid",
                "ide_checkpoint_scope_forbidden",
                "ide_checkpoint_integrity_failed",
                "ide_checkpoint_storage_unavailable",
                "ide_checkpoint_intent_mismatch",
                "ide_checkpoint_status_unknown",
                "ide_checkpoint_runtime_not_ready",
                "ide_checkpoint_not_published",
                "ide_checkpoint_storage_changed",
                "ide_checkpoint_capture_unavailable",
                "ide_checkpoint_restore_unavailable",
                "ide_checkpoint_restore_pending",
                "ide_checkpoint_cleanup_unavailable",
                "ide_checkpoint_quota_exceeded",
                "ide_checkpoint_pending",
                "ide_checkpoint_head_changed",
                "ide_checkpoint_not_discardable",
                "ide_checkpoint_not_abandonable",
            }
            else "ide_checkpoint_invalid"
        )
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CheckpointBlob:
    scope: RepositoryScope = field(repr=False)
    checkpoint_id: UUID
    sha256: str = field(repr=False)
    size: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scope, RepositoryScope)
            or not all(isinstance(value, UUID) for value in self.scope.params().values())
            or not isinstance(self.checkpoint_id, UUID)
            or not isinstance(self.sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.sha256)
            or type(self.size) is not int
            or not 0 <= self.size < 2**63 - 1
        ):
            raise IdeCheckpointError()

    def key_for(self, scope: RepositoryScope) -> str:
        if scope != self.scope:
            raise IdeCheckpointError("ide_checkpoint_scope_forbidden")
        # Never accept a key, URL, filename or sandbox root from the browser.
        # Different content cannot overwrite a previously addressed blob.
        identity = (
            b"gpthub:ide-checkpoint:v1|"
            + scope.user_id.bytes
            + scope.thread_id.bytes
            + scope.repository_id.bytes
            + self.checkpoint_id.bytes
            + self.size.to_bytes(8, "big")
            + bytes.fromhex(self.sha256)
        )
        # Fixed-size opaque names also work in the local Windows backend. The
        # owned metadata, not listing a guessed user prefix, owns retention.
        address = hashlib.sha256(identity).hexdigest()
        return f"ide-checkpoints/v1/{address[:2]}/{address[2:]}"
