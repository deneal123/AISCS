"""Application owner for explicit Save/history/restore; no client storage locators."""

import time
from typing import Any
from uuid import UUID

from service.infrastructure.ide.transports.capture import CapturePolicy
from service.services.chat.application.ide.checkpoints.capture import capture_checkpoint
from service.services.chat.application.ide.checkpoints.restore import IdeRestoreService
from service.services.chat.application.ide.checkpoints.service import IdeCheckpointService
from service.services.chat.application.ide.edits import IdeEditService
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.checkpoints.blob import IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.restore import RestoreRecord
from service.services.chat.domain.ide.checkpoints.revision import CheckpointRecord
from service.services.chat.domain.ide.runtime import RepositoryScope, generation_tag


def public_checkpoint(record: CheckpointRecord) -> dict[str, Any]:
    return {
        "repository_id": str(record.intent.blob.scope.repository_id),
        "checkpoint_id": str(record.intent.blob.checkpoint_id),
        "state": record.state,
        "is_current": record.is_current,
        "current_checkpoint_id": str(record.current_checkpoint_id)
        if record.current_checkpoint_id
        else None,
        "size_bytes": record.intent.blob.size,
        "can_discard": record.state in {"pending", "retired", "conflict"}
        and record.upload_settled
        and not record.collected
        and record.current_checkpoint_id != record.intent.blob.checkpoint_id,
        "collected": record.collected,
        "can_abandon": record.state == "pending"
        and record.current_checkpoint_id != record.intent.blob.checkpoint_id,
    }


class IdeSavedProjects:
    def __init__(
        self,
        edits: IdeEditService,
        checkpoints: IdeCheckpointService,
        restores: IdeRestoreService,
        *,
        limits: CapturePolicy,
    ) -> None:
        if (
            checkpoints.budget is None
            or checkpoints.retention is None
            or not checkpoints.historical
            or limits.archive_bytes > checkpoints.budget.max_checkpoint_bytes
        ):
            raise ValueError("public_checkpoint_policy_required")
        self.edits, self.checkpoints, self.restores, self.limits = (
            edits,
            checkpoints,
            restores,
            limits,
        )

    async def _owner(self, scope: RepositoryScope) -> None:
        if await self.edits.runtime.repository.get_owned(**scope.params()) is None:
            raise IdeRepositoryNotFound

    async def history(self, scope: RepositoryScope) -> dict[str, Any]:
        await self._owner(scope)
        rows = await self.checkpoints.repository.inventory(scope)
        if rows is None:
            raise IdeRepositoryNotFound
        attempt = await self.edits.runtime.runtime.get_owned(scope)
        latest_restore = await self.restores.repository.latest_owned(scope)
        budget = self.checkpoints.budget
        if budget is None:
            raise IdeCheckpointError()
        # Select individual public fields; never return SQL rows/capsule identity.
        items = [
            {
                "checkpoint_id": str(row["checkpoint_id"]),
                "state": row["state"],
                "size_bytes": row["size"],
                "created_at": row["created_at"],
                "published_at": row["published_at"],
                "is_current": row["state"] == "published"
                and row["checkpoint_id"] == row["current_checkpoint_id"],
                "can_discard": row["state"] in {"pending", "retired", "conflict"}
                and row.get("upload_settled_at") is not None
                and row["checkpoint_id"] != row["current_checkpoint_id"],
                "can_abandon": row["state"] == "pending"
                and row["checkpoint_id"] != row["current_checkpoint_id"],
            }
            for row in rows[:32]
        ]
        return {
            "repository_id": str(scope.repository_id),
            "items": items,
            "truncated": len(rows) > 32,
            "last_restore": await self._restore_view(scope, latest_restore)
            if latest_restore
            else None,
            "usage": {
                "used_bytes": await self.checkpoints.repository.accounted_bytes(scope.user_id),
                "max_bytes": budget.max_user_bytes,
                "max_snapshot_bytes": budget.max_checkpoint_bytes,
            },
            "runtime": {
                "generation": generation_tag(attempt) if attempt else None,
                "state": "expired"
                if attempt and attempt.expires_at <= time.time()
                else attempt.state
                if attempt
                else "not_created",
            },
        }

    async def save(
        self,
        scope: RepositoryScope,
        *,
        checkpoint_id: UUID,
        base_checkpoint_id: UUID | None,
        generation: str,
        session: str | None,
    ) -> dict[str, Any]:
        await self._owner(scope)
        result = await capture_checkpoint(
            self.edits,
            self.checkpoints,
            scope,
            checkpoint_id=checkpoint_id,
            base_checkpoint_id=base_checkpoint_id,
            generation=generation,
            session=session,
            limits=self.limits,
        )
        return public_checkpoint(result)

    async def status(self, scope: RepositoryScope, checkpoint_id: UUID) -> dict[str, Any]:
        return public_checkpoint(await self.checkpoints.status(scope, checkpoint_id))

    async def reconcile(self, scope: RepositoryScope, checkpoint_id: UUID) -> dict[str, Any]:
        return public_checkpoint(await self.checkpoints.reconcile(scope, checkpoint_id))

    async def discard(self, scope: RepositoryScope, checkpoint_id: UUID) -> dict[str, Any]:
        record, allowed = await self.checkpoints.repository.abandon_pending(scope, checkpoint_id)
        if record is None:
            raise IdeRepositoryNotFound
        if not allowed:
            raise IdeCheckpointError("ide_checkpoint_not_discardable")
        retention = self.checkpoints.retention
        if retention is None:
            raise IdeCheckpointError("ide_checkpoint_cleanup_unavailable")
        result = await retention.collect_record(scope, record)
        response = public_checkpoint(await self.checkpoints.status(scope, checkpoint_id))
        response["cleanup_pending"] = result.pending
        return response

    async def abandon(self, scope: RepositoryScope, checkpoint_id: UUID) -> dict[str, Any]:
        record, allowed = await self.checkpoints.repository.revoke_pending(scope, checkpoint_id)
        if record is None:
            raise IdeRepositoryNotFound
        if not allowed:
            raise IdeCheckpointError("ide_checkpoint_not_abandonable")
        return public_checkpoint(record)

    async def restore(
        self, scope: RepositoryScope, *, restore_id: UUID, checkpoint_id: UUID, base_generation: str
    ) -> dict[str, Any]:
        await self._owner(scope)
        try:
            previous = await self.restores.status(scope, restore_id)
        except IdeRepositoryNotFound:
            previous = None
        if previous is not None:
            from service.services.chat.domain.ide.runtime import allocation_generation_tag

            if (
                previous.blob.checkpoint_id != checkpoint_id
                or allocation_generation_tag(previous.base_allocation_id) != base_generation
            ):
                raise IdeCheckpointError("ide_checkpoint_intent_mismatch")
            result = await self.restores.reconcile(scope, restore_id)
        else:
            attempt = await self.edits.runtime.runtime.get_owned(scope)
            if attempt is None or generation_tag(attempt) != base_generation:
                raise IdeCheckpointError("ide_checkpoint_runtime_not_ready")
            result = await self.restores.restore(
                scope, restore_id, checkpoint_id, attempt.allocation_id
            )
        return await self._restore_view(scope, result)

    async def restore_status(self, scope: RepositoryScope, restore_id: UUID) -> dict[str, Any]:
        return await self._restore_view(scope, await self.restores.status(scope, restore_id))

    async def reconcile_restore(self, scope: RepositoryScope, restore_id: UUID) -> dict[str, Any]:
        return await self._restore_view(scope, await self.restores.reconcile(scope, restore_id))

    async def _restore_view(self, scope: RepositoryScope, record: RestoreRecord) -> dict[str, Any]:
        current = await self.edits.runtime.runtime.get_owned(scope)
        active = (
            record.state == "published"
            and current is not None
            and current.allocation_id == record.allocation_id
            and current.expires_at == record.expires_at
            and current.state == "ready"
            and current.expires_at > time.time()
        )
        return {
            "repository_id": str(scope.repository_id),
            "restore_id": str(record.restore_id),
            "checkpoint_id": str(record.blob.checkpoint_id),
            "state": record.state,
            "active": active,
            "generation": generation_tag(current) if active and current else None,
        }
