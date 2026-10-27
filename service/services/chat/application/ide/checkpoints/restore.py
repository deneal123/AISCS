"""Private explicit restore coordinator. No public route, auto-restore or retention.

Claim commits before bytes are opened. A replay/lost commit ACK only looks up
the original native allocation; it never uploads again or prolongs its deadline.
"""

from __future__ import annotations

import time
from dataclasses import replace
from uuid import UUID

from service.infrastructure.ide.transports.capture import CapturePolicy
from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.services.chat.application.ide.checkpoints.service import IdeCheckpointService
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.checkpoints.blob import IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.restore import RestoreRecord
from service.services.chat.domain.ide.runtime import RepositoryScope, RuntimeObservation
from service.services.chat.persistence.ide.checkpoints.restore import IdeRestoreRepository
from service.shared.repositories.exceptions import RepositoryError


class IdeRestoreService:
    def __init__(
        self,
        repository: IdeRestoreRepository,
        checkpoints: IdeCheckpointService,
        client: IdeWorkspaceClient,
        *,
        limits: CapturePolicy,
    ) -> None:
        self.repository, self.checkpoints, self.client, self.limits = (
            repository,
            checkpoints,
            client,
            limits,
        )

    async def status(self, scope: RepositoryScope, restore_id: UUID) -> RestoreRecord:
        try:
            record = await self.repository.get_owned(scope, restore_id)
        except RepositoryError:
            raise IdeCheckpointError("ide_checkpoint_status_unknown") from None
        if record is None:
            raise IdeRepositoryNotFound
        return record

    async def restore(
        self,
        scope: RepositoryScope,
        restore_id: UUID,
        checkpoint_id: UUID,
        base_allocation_id: UUID,
    ) -> RestoreRecord:
        try:
            existing = await self.repository.get_owned(scope, restore_id)
        except RepositoryError:
            raise IdeCheckpointError("ide_checkpoint_status_unknown") from None
        if existing is not None:
            self._match(existing, checkpoint_id, base_allocation_id)
            return await self.reconcile(scope, restore_id)
        saved = await self.checkpoints.status(scope, checkpoint_id)
        if saved.state != "published":
            raise IdeCheckpointError("ide_checkpoint_not_published")
        if (
            saved.intent.storage_namespace != self.checkpoints.storage.namespace
            or not isinstance(self.limits, CapturePolicy)
            or not 0 < saved.intent.blob.size <= self.limits.archive_bytes
        ):
            raise IdeCheckpointError("ide_checkpoint_restore_unavailable")
        ttl = await self.client.allocation_ttl()
        if ttl is None:
            raise IdeCheckpointError("ide_checkpoint_restore_unavailable")
        try:
            claim = await self.repository.reserve(
                scope, restore_id, checkpoint_id, base_allocation_id, ttl_sec=ttl
            )
        except RepositoryError:
            # No dispatch after uncertain commit, even if its exact row is now
            # visible. The caller can explicitly reconcile this identity later.
            try:
                record = await self.status(scope, restore_id)
            except IdeRepositoryNotFound:
                raise IdeCheckpointError("ide_checkpoint_status_unknown") from None
            self._match(record, checkpoint_id, base_allocation_id)
            return record
        if claim.failure == "missing":
            raise IdeRepositoryNotFound
        if claim.failure:
            raise IdeCheckpointError(
                {
                    "checkpoint_not_published": "ide_checkpoint_not_published",
                    "runtime_not_expired": "ide_checkpoint_runtime_not_ready",
                    "restore_pending": "ide_checkpoint_restore_pending",
                    "command_busy": "ide_command_busy",
                }[claim.failure]
            )
        if claim.record is None:
            raise IdeCheckpointError("ide_checkpoint_status_unknown")
        record = claim.record
        self._match(record, checkpoint_id, base_allocation_id)
        if not claim.dispatch:
            return await self.reconcile(scope, restore_id)
        if record.expires_at <= time.time():
            return await self._finish(scope, record, RuntimeObservation("expired"))
        async with self.checkpoints.open_saved(scope, checkpoint_id) as (current, source):
            if (
                current.intent.blob != record.blob
                or current.intent.storage_namespace != record.storage_namespace
            ):
                raise IdeCheckpointError("ide_checkpoint_intent_mismatch")
            observation = await self.client.restore(
                scope, record.attempt(dispatch=True), record.blob, source=source, limits=self.limits
            )
        return await self._finish(scope, record, observation)

    async def reconcile(self, scope: RepositoryScope, restore_id: UUID) -> RestoreRecord:
        record = await self.status(scope, restore_id)
        if record.state != "pending":
            return record
        observation = RuntimeObservation("expired")
        if record.expires_at > time.time():
            observation = await self.client.restore(scope, record.attempt(), record.blob)
        return await self._finish(scope, record, observation)

    @staticmethod
    def _match(record: RestoreRecord, checkpoint_id: UUID, base_allocation_id: UUID) -> None:
        if not record.matches(checkpoint_id, base_allocation_id):
            raise IdeCheckpointError("ide_checkpoint_intent_mismatch")

    async def _finish(
        self, scope: RepositoryScope, record: RestoreRecord, observation: RuntimeObservation
    ) -> RestoreRecord:
        verified = (
            observation.state == "ready"
            and observation.binding is not None
            and observation.binding.expires_at == record.expires_at
        )
        try:
            current = await self.repository.publish(scope, record.restore_id, verified=verified)
        except RepositoryError:
            current = await self.status(scope, record.restore_id)
        if current is None:
            raise IdeRepositoryNotFound
        if replace(current, state=record.state) != record:
            raise IdeCheckpointError("ide_checkpoint_intent_mismatch")
        return current
