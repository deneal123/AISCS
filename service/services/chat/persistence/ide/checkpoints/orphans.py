"""Private cleanup ledger after descriptor deletion, never an authorization fallback."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.chat.domain.ide.checkpoints.revision import CheckpointIntent, CheckpointRecord
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

# Absence of an owned join is insufficient: a descriptor with ANY owner blocks
# orphan cleanup. Restore pins must first be explicitly revoked in this ledger;
# absence or expiry alone does not masquerade as a completed restore.
_DESCRIPTOR_ABSENT = (
    "NOT EXISTS (SELECT 1 FROM profile.ide_repository r WHERE r.repository_id=c.repository_id)"
)
_ORPHAN = (
    _DESCRIPTOR_ABSENT + " AND c.command_pins=0 "
    "AND NOT EXISTS (SELECT 1 FROM profile.ide_repository_head h "
    "WHERE h.repository_id=c.repository_id AND h.checkpoint_id=c.checkpoint_id) "
    "AND NOT EXISTS (SELECT 1 FROM profile.ide_restore_intent i "
    "WHERE i.repository_id=c.repository_id AND i.active_checkpoint_id=c.checkpoint_id)"
)
_EXACT = (
    "c.repository_id=:repository_id AND c.checkpoint_id=:checkpoint_id "
    "AND c.thread_id=:thread_id AND c.user_id=:user_id "
    "AND c.allocation_id=:allocation_id AND c.sha256=:sha256 AND c.size=:size "
    "AND c.storage_namespace=:storage_namespace "
    "AND c.base_checkpoint_id IS NOT DISTINCT FROM :base_checkpoint_id"
)


async def settle_orphan_upload(
    session: AsyncSession, intent: CheckpointIntent
) -> CheckpointRecord | None:
    """The original trusted uploader may finish its exact receipt after chat deletion.

    This never publishes or frees accounting and is not reachable from status or
    reconciliation. An absent receipt is never inferred from age/object existence.
    """
    result = await session.execute(
        text(
            "UPDATE profile.ide_checkpoint_intent c SET upload_settled_at=coalesce("
            "upload_settled_at,clock_timestamp()) WHERE "
            + _EXACT
            + " AND c.collected_at IS NULL AND "
            + _DESCRIPTOR_ABSENT
            + " RETURNING c.*,NULL::uuid AS current_checkpoint_id"
        ),
        intent.params(),
    )
    return CheckpointRecord.from_row(result.mappings().first())


class IdeCheckpointOrphanRepository(BaseRepository):
    @connection()
    async def revoke_restore_publication(
        self,
        *,
        storage_namespace: str,
        limit: int = 32,
        session: AsyncSession | None = None,
    ) -> int:
        """Descriptor deletion revokes publication, not native allocation lifetime.

        Restore consumes an immutable download and cannot write the checkpoint
        key. An in-flight reader may fail after owner deletion, but cannot publish
        into a deleted repository. Keep the exact private allocation/expiry ledger
        for runtime cleanup; never report that the workspace itself was stopped.
        No live descriptor, even with a different owner, may lose its restore pin.
        """
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("invalid_checkpoint_orphan_limit")
        result = await require_session(session).execute(
            text(
                "WITH candidates AS (SELECT i.repository_id,i.restore_id "
                "FROM profile.ide_restore_intent i WHERE i.state='pending' "
                "AND i.storage_namespace=:namespace "
                "AND NOT EXISTS (SELECT 1 FROM profile.ide_repository r "
                "WHERE r.repository_id=i.repository_id) "
                "ORDER BY i.repository_id,i.restore_id LIMIT :limit "
                "FOR UPDATE OF i SKIP LOCKED) "
                "UPDATE profile.ide_restore_intent i SET state='conflict',"
                "active_checkpoint_id=NULL,updated_at=clock_timestamp() FROM candidates k "
                "WHERE i.repository_id=k.repository_id AND i.restore_id=k.restore_id "
                "RETURNING i.restore_id"
            ),
            {"namespace": storage_namespace, "limit": limit},
        )
        return len(result.all())

    @connection()
    async def retire_batch(
        self,
        *,
        storage_namespace: str,
        limit: int = 32,
        after: tuple[UUID, UUID] | None = None,
        session: AsyncSession | None = None,
    ) -> list[CheckpointRecord]:
        """Commit tombstones before returning any exact object for storage I/O."""
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("invalid_checkpoint_orphan_limit")
        if after is not None and (
            not isinstance(after, tuple)
            or len(after) != 2
            or not all(isinstance(value, UUID) for value in after)
        ):
            raise ValueError("invalid_checkpoint_orphan_cursor")
        result = await require_session(session).execute(
            text(
                "WITH candidates AS (SELECT c.repository_id,c.checkpoint_id "
                "FROM profile.ide_checkpoint_intent c WHERE c.storage_namespace=:namespace "
                "AND c.upload_settled_at IS NOT NULL AND c.collected_at IS NULL "
                "AND (c.repository_id,c.checkpoint_id)>(:after_repo,:after_checkpoint) AND "
                + _ORPHAN
                + " ORDER BY c.repository_id,c.checkpoint_id LIMIT :limit "
                "FOR UPDATE OF c SKIP LOCKED) "
                "UPDATE profile.ide_checkpoint_intent c SET state='retired',published_at=NULL,"
                "updated_at=clock_timestamp() FROM candidates k "
                "WHERE c.repository_id=k.repository_id AND c.checkpoint_id=k.checkpoint_id "
                "RETURNING c.*,NULL::uuid AS current_checkpoint_id"
            ),
            {
                "namespace": storage_namespace,
                "limit": limit,
                "after_repo": after[0] if after else UUID(int=0),
                "after_checkpoint": after[1] if after else UUID(int=0),
            },
        )
        records = [CheckpointRecord.from_row(row) for row in result.mappings().all()]
        # UPDATE RETURNING has no ordering guarantee; pagination must not skip
        # the unreturned tail or replay only the first failed deletion forever.
        return sorted(
            (record for record in records if record is not None),
            key=lambda record: (
                record.intent.blob.scope.repository_id,
                record.intent.blob.checkpoint_id,
            ),
        )

    @connection()
    async def acknowledge_discard(
        self, intent: CheckpointIntent, *, session: AsyncSession | None = None
    ) -> bool:
        result = await require_session(session).execute(
            text(
                "UPDATE profile.ide_checkpoint_intent c SET collected_at=clock_timestamp(),"
                "updated_at=clock_timestamp() WHERE "
                + _EXACT
                + " AND c.state='retired' AND c.upload_settled_at IS NOT NULL "
                "AND c.collected_at IS NULL AND " + _ORPHAN + " RETURNING c.checkpoint_id"
            ),
            intent.params(),
        )
        return result.first() is not None
