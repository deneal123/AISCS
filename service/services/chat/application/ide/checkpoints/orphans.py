"""Maintenance-only collection of settled snapshots with no remaining descriptor."""

from dataclasses import dataclass, field
from uuid import UUID

from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.services.chat.domain.ide.checkpoints.blob import IdeCheckpointError
from service.services.chat.persistence.ide.checkpoints.orphans import IdeCheckpointOrphanRepository
from service.shared.repositories.exceptions import RepositoryError


@dataclass(frozen=True, slots=True)
class OrphanSweepResult:
    examined: int
    delete_acknowledged: int
    pending: int
    cursor: tuple[UUID, UUID] | None = field(repr=False)
    restore_publications_revoked: int = 0


class IdeCheckpointOrphanService:
    def __init__(
        self, repository: IdeCheckpointOrphanRepository, storage: IdeCheckpointStorage
    ) -> None:
        self.repository, self.storage = repository, storage

    async def sweep(
        self, *, limit: int = 32, after: tuple[UUID, UUID] | None = None
    ) -> OrphanSweepResult:
        # Decorator-owned transaction commits retirement before physical I/O.
        # A lost commit ACK propagates: never delete a guessed candidate.
        revoked = await self.repository.revoke_restore_publication(
            storage_namespace=self.storage.namespace, limit=limit
        )
        records = await self.repository.retire_batch(
            storage_namespace=self.storage.namespace, limit=limit, after=after
        )
        acknowledged = pending = 0
        for record in records:
            blob = record.intent.blob
            if (
                record.state != "retired"
                or record.current_checkpoint_id == blob.checkpoint_id
                or not record.upload_settled
                or record.collected
                or record.intent.storage_namespace != self.storage.namespace
            ):
                pending += 1
                continue
            try:
                await self.storage.discard(blob.scope, blob)
            except IdeCheckpointError:
                pending += 1
                continue
            acknowledged += 1
            try:
                confirmed = await self.repository.acknowledge_discard(record.intent)
            except RepositoryError:
                confirmed = False
            pending += int(not confirmed)
        last = records[-1].intent.blob if records else None
        return OrphanSweepResult(
            len(records),
            acknowledged,
            pending,
            (last.scope.repository_id, last.checkpoint_id) if last else None,
            restore_publications_revoked=revoked,
        )
