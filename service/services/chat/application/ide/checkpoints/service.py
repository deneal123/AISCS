"""Explicit checkpoint publication; no runtime capture, file writes or allocation.

Only trusted capture/lease owners may supply an intent and source. Public IDE
composition additionally requires budget, retention and fenced runtime capture.
A blob upload alone is never a saved revision. Reconciliation can verify and
publish its frozen bytes after writer loss without inventing a cleanup receipt.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import BinaryIO
from uuid import UUID

from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.services.chat.application.ide.checkpoints.retention import (
    IdeCheckpointRetentionService,
)
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.checkpoints.blob import IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.budget import CheckpointStorageBudget
from service.services.chat.domain.ide.checkpoints.revision import CheckpointIntent, CheckpointRecord
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.checkpoints.repository import IdeCheckpointRepository
from service.shared.repositories.exceptions import RepositoryError


def _matched(record: CheckpointRecord | None, intent: CheckpointIntent) -> CheckpointRecord:
    if record is None:
        raise IdeRepositoryNotFound
    if record.intent != intent:
        raise IdeCheckpointError("ide_checkpoint_intent_mismatch")
    return record


class IdeCheckpointService:
    def __init__(
        self,
        repository: IdeCheckpointRepository,
        storage: IdeCheckpointStorage,
        *,
        retention: IdeCheckpointRetentionService | None = None,
        budget: CheckpointStorageBudget | None = None,
        historical: bool = False,
    ) -> None:
        self.repository, self.storage = repository, storage
        self.retention = retention
        self.budget = budget
        self.historical = historical

    def _check_storage(self, intent: CheckpointIntent) -> None:
        if intent.storage_namespace != self.storage.namespace:
            raise IdeCheckpointError("ide_checkpoint_storage_changed")

    async def status(self, scope: RepositoryScope, checkpoint_id: UUID) -> CheckpointRecord:
        """Passive, including after expiry. No upload, head advance or runtime probe."""
        try:
            record = await self.repository.get_owned(scope, checkpoint_id)
        except RepositoryError:
            raise IdeCheckpointError("ide_checkpoint_status_unknown") from None
        if record is None:
            raise IdeRepositoryNotFound
        return record

    @asynccontextmanager
    async def open_saved(
        self, scope: RepositoryScope, checkpoint_id: UUID
    ) -> AsyncIterator[tuple[CheckpointRecord, BinaryIO]]:
        """Read one explicit published revision, independent of runtime lifetime.

        The caller chose this revision, not a mutable global HEAD. An older
        published revision remains historical if HEAD moves during download.
        Recheck ownership before exposing bytes; never promote a pending blob.
        """
        record = await self.status(scope, checkpoint_id)
        if record.state != "published":
            raise IdeCheckpointError("ide_checkpoint_not_published")
        self._check_storage(record.intent)
        async with self.storage.open(scope, record.intent.blob) as source:
            self._check_storage(record.intent)
            current = _matched(await self.status(scope, checkpoint_id), record.intent)
            if current.state != "published":
                raise IdeCheckpointError("ide_checkpoint_not_published")
            yield current, source

    async def save(
        self, scope: RepositoryScope, intent: CheckpointIntent, source: BinaryIO
    ) -> CheckpointRecord:
        intent.blob.key_for(scope)
        self._check_storage(intent)
        if intent.blob.size > self.storage.max_bytes:
            raise IdeCheckpointError()
        try:
            reservation = (
                await self.repository.reserve(intent, budget=self.budget)
                if self.budget
                else await self.repository.reserve(intent)
            )
        except RepositoryError:
            # A lost claim/commit acknowledgement cannot dispatch a new upload.
            # Read the exact intent in a fresh transaction, even if still pending.
            return _matched(await self._uncertain_status(scope, intent.blob.checkpoint_id), intent)
        if reservation.failure == "missing":
            raise IdeRepositoryNotFound
        if reservation.failure:
            raise IdeCheckpointError(
                {
                    "quota": "ide_checkpoint_quota_exceeded",
                    "pending": "ide_checkpoint_pending",
                    "head_changed": "ide_checkpoint_head_changed",
                }.get(reservation.failure, "ide_checkpoint_runtime_not_ready")
            )
        _matched(reservation.record, intent)
        if not reservation.dispatch:
            # A replay observes/reconciles only; a changed payload cannot reuse
            # an old intent, and a published old checkpoint cannot roll back HEAD.
            return await self.reconcile(scope, intent.blob.checkpoint_id)
        try:
            await self.storage.put(scope, intent.blob, source)
        except BaseException:
            if self.budget is not None:
                try:
                    settled = await self.repository.mark_upload_settled(intent)
                    if settled is not None and settled.intent == intent:
                        await self._collect_revoked(scope, settled)
                except RepositoryError:
                    pass
            raise
        if self.budget is not None:
            try:
                _matched(await self.repository.mark_upload_settled(intent), intent)
            except RepositoryError:
                return _matched(
                    await self._uncertain_status(scope, intent.blob.checkpoint_id), intent
                )
        return await self._publish(scope, intent)

    async def reconcile(self, scope: RepositoryScope, checkpoint_id: UUID) -> CheckpointRecord:
        """Explicit recovery of one known intent. Never re-upload or delete bytes."""
        record = await self.status(scope, checkpoint_id)
        if record.state != "pending":
            return record
        if not self.historical and record.current_checkpoint_id != record.intent.base_checkpoint_id:
            # A superseded claim can be terminal even if its upload never ran.
            # Do not wait on a missing/unavailable object that cannot become HEAD.
            record = await self._publish(scope, record.intent, verified=False)
            if record.state != "pending":
                return record
        self._check_storage(record.intent)
        async with self.storage.open(scope, record.intent.blob):
            pass
        return await self._publish(scope, record.intent)

    async def _publish(
        self, scope: RepositoryScope, intent: CheckpointIntent, *, verified: bool = True
    ) -> CheckpointRecord:
        if verified:
            self._check_storage(intent)
        try:
            if self.historical:
                record = await self.repository.publish(
                    scope, intent.blob.checkpoint_id, verified=verified, historical=True
                )
            else:
                record = await self.repository.publish(
                    scope, intent.blob.checkpoint_id, verified=verified
                )
        except RepositoryError:
            record = await self._uncertain_status(scope, intent.blob.checkpoint_id)
        matched = _matched(record, intent)
        if (
            self.retention is not None
            and matched.state == "published"
            and (matched.is_current or self.historical)
        ):
            # Publication is already acknowledged. Cleanup failure must not
            # turn a saved snapshot into a failed Save or repeat its upload.
            try:
                await self.retention.run(scope, intent.blob.checkpoint_id)
            except IdeCheckpointError:
                pass
        await self._collect_revoked(scope, matched)
        return matched

    async def _collect_revoked(self, scope: RepositoryScope, record: CheckpointRecord) -> None:
        # An explicitly revoked public attempt cannot publish after its writer
        # returns, even on failure. Only actual settlement permits collection.
        if (
            self.retention is not None
            and self.historical
            and self.budget is not None
            and record.state == "retired"
            and record.upload_settled
        ):
            try:
                await self.retention.collect_record(scope, record)
            except IdeCheckpointError:
                pass

    async def _uncertain_status(
        self, scope: RepositoryScope, checkpoint_id: UUID
    ) -> CheckpointRecord:
        try:
            return await self.status(scope, checkpoint_id)
        except IdeRepositoryNotFound:
            # Missing after an uncertain commit is not proof that it rolled back.
            raise IdeCheckpointError("ide_checkpoint_status_unknown") from None
