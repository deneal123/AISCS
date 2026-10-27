"""Explicit post-publication cleanup, never a best-effort delete before commit."""

from dataclasses import dataclass, field
from uuid import UUID

from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.services.chat.domain.ide.checkpoints.blob import IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.revision import CheckpointRecord
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.checkpoints.retention import (
    IdeCheckpointRetentionRepository,
)
from service.shared.repositories.exceptions import RepositoryError


@dataclass(frozen=True, slots=True)
class RetentionResult:
    acknowledged: int = 0
    pending: bool = False


@dataclass(frozen=True, slots=True)
class SweepResult:
    repositories: int
    delete_acknowledged: int
    pending: int
    cursor: UUID | None = field(repr=False)


class IdeCheckpointRetentionService:
    def __init__(
        self, repository: IdeCheckpointRetentionRepository, storage: IdeCheckpointStorage
    ) -> None:
        self.repository, self.storage = repository, storage

    async def sweep(
        self, *, limit: int = 32, after_repository_id: UUID | None = None
    ) -> SweepResult:
        """Retry committed retirement/cleanup without recreating a lost writer receipt."""
        scopes = await self.repository.maintenance_scopes(
            storage_namespace=self.storage.namespace,
            limit=limit,
            after_repository_id=after_repository_id,
        )
        acknowledged, pending = 0, 0
        for scope, head in scopes:
            if head is not None:
                result = await self.run(scope, head)
                acknowledged += result.acknowledged
                pending += int(result.pending)
                continue
            try:
                records = await self.repository.pending_cleanup(
                    scope, storage_namespace=self.storage.namespace
                )
            except RepositoryError:
                pending += 1
                continue
            for record in records:
                result = await self.collect_record(scope, record)
                acknowledged += result.acknowledged
                pending += int(result.pending)
        return SweepResult(
            len(scopes), acknowledged, pending, scopes[-1][0].repository_id if scopes else None
        )

    async def run(self, scope: RepositoryScope, checkpoint_id: UUID) -> RetentionResult:
        try:
            records = await self.repository.retire_history(
                scope, after_checkpoint_id=checkpoint_id, storage_namespace=self.storage.namespace
            )
        except RepositoryError:
            # Lost commit ACK is not permission to delete guessed candidates.
            return RetentionResult(pending=True)
        acknowledged, pending = 0, False
        for record in records:
            result = await self.collect_record(scope, record)
            acknowledged += result.acknowledged
            pending = pending or result.pending
        return RetentionResult(acknowledged, pending)

    async def collect_record(
        self, scope: RepositoryScope, record: CheckpointRecord
    ) -> RetentionResult:
        if (
            record.state not in {"retired", "conflict"}
            or record.current_checkpoint_id == record.intent.blob.checkpoint_id
        ):
            raise IdeCheckpointError("ide_checkpoint_cleanup_unavailable")
        if record.collected:
            return RetentionResult()
        if not record.upload_settled or record.intent.storage_namespace != self.storage.namespace:
            return RetentionResult(pending=True)
        try:
            await self.storage.discard(scope, record.intent.blob)
        except IdeCheckpointError:
            return RetentionResult(pending=True)
        try:
            confirmed = await self.repository.acknowledge_discard(record.intent)
        except RepositoryError:
            return RetentionResult(acknowledged=1, pending=True)
        return RetentionResult(acknowledged=1, pending=not confirmed)
