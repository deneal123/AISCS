"""Owned history retirement; object I/O follows the committed tombstones."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.chat.domain.ide.checkpoints.revision import CheckpointIntent, CheckpointRecord
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.checkpoints.repository import _lock_owner
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

# Product policy delegated by the user on 18.10.2026. Active restore pins may
# temporarily retain extra versions; they are never evicted to meet this count.
RETAINED_CHECKPOINTS = 11


class IdeCheckpointRetentionRepository(BaseRepository):
    @connection()
    async def maintenance_scopes(
        self,
        *,
        storage_namespace: str,
        limit: int = 32,
        after_repository_id: UUID | None = None,
        session: AsyncSession | None = None,
    ) -> list[tuple[RepositoryScope, UUID | None]]:
        """Bounded discovery only; deletion still requires a committed owned re-read."""
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError("invalid_checkpoint_maintenance_limit")
        if after_repository_id is not None and not isinstance(after_repository_id, UUID):
            raise ValueError("invalid_checkpoint_maintenance_cursor")
        result = await require_session(session).execute(
            text(
                "SELECT r.thread_id,r.user_id,r.repository_id,h.checkpoint_id "
                "FROM profile.ide_repository r "
                "JOIN profile.chat_threads t ON t.thread_id=r.thread_id AND t.user_id=r.user_id "
                "LEFT JOIN profile.ide_repository_head h ON h.repository_id=r.repository_id "
                "WHERE r.repository_id>:after_repository_id AND (EXISTS "
                "(SELECT 1 FROM profile.ide_checkpoint_intent c "
                "WHERE c.repository_id=r.repository_id AND c.thread_id=r.thread_id "
                "AND c.user_id=r.user_id AND c.storage_namespace=:storage_namespace "
                "AND c.state IN ('retired','conflict') AND c.collected_at IS NULL "
                "AND c.command_pins=0 "
                "AND c.upload_settled_at IS NOT NULL "
                "AND c.checkpoint_id IS DISTINCT FROM h.checkpoint_id "
                "AND NOT EXISTS (SELECT 1 FROM profile.ide_restore_intent i "
                "WHERE i.repository_id=c.repository_id "
                "AND i.active_checkpoint_id=c.checkpoint_id)) "
                "OR (h.checkpoint_id IS NOT NULL AND EXISTS (SELECT 1 "
                "FROM profile.ide_checkpoint_intent c WHERE c.repository_id=r.repository_id "
                "AND c.thread_id=r.thread_id AND c.user_id=r.user_id "
                "AND c.checkpoint_id=h.checkpoint_id AND c.state='published' "
                "AND c.storage_namespace=:storage_namespace) AND (SELECT count(*) "
                "FROM profile.ide_checkpoint_intent c WHERE c.repository_id=r.repository_id "
                "AND c.thread_id=r.thread_id AND c.user_id=r.user_id "
                "AND c.state='published')>:keep)) "
                "ORDER BY r.repository_id LIMIT :limit"
            ),
            {
                "storage_namespace": storage_namespace,
                "keep": RETAINED_CHECKPOINTS,
                "limit": limit,
                "after_repository_id": after_repository_id or UUID(int=0),
            },
        )
        return [
            (
                RepositoryScope(row["thread_id"], row["user_id"], row["repository_id"]),
                row["checkpoint_id"],
            )
            for row in result.mappings().all()
        ]

    @connection()
    async def pending_cleanup(
        self,
        scope: RepositoryScope,
        *,
        storage_namespace: str,
        session: AsyncSession | None = None,
    ) -> list[CheckpointRecord]:
        session = require_session(session)
        if not await _lock_owner(session, scope):
            return []
        return await self._pending_cleanup(session, scope, storage_namespace)

    @staticmethod
    async def _pending_cleanup(
        session: AsyncSession,
        scope: RepositoryScope,
        storage_namespace: str,
    ) -> list[CheckpointRecord]:
        result = await session.execute(
            text(
                "SELECT c.*,h.checkpoint_id AS current_checkpoint_id "
                "FROM profile.ide_checkpoint_intent c "
                "LEFT JOIN profile.ide_repository_head h ON h.repository_id=c.repository_id "
                "WHERE c.repository_id=:repository_id AND c.thread_id=:thread_id "
                "AND c.user_id=:user_id AND c.state IN ('retired','conflict') "
                "AND c.command_pins=0 "
                "AND c.upload_settled_at IS NOT NULL AND c.collected_at IS NULL "
                "AND c.storage_namespace=:storage_namespace "
                "AND c.checkpoint_id IS DISTINCT FROM h.checkpoint_id "
                "AND NOT EXISTS (SELECT 1 FROM profile.ide_restore_intent i "
                "WHERE i.repository_id=c.repository_id AND i.active_checkpoint_id=c.checkpoint_id) "
                "ORDER BY c.updated_at,c.checkpoint_id LIMIT 32"
            ),
            {**scope.params(), "storage_namespace": storage_namespace},
        )
        return [
            record
            for row in result.mappings().all()
            if (record := CheckpointRecord.from_row(row)) is not None
        ]

    @connection()
    async def retire_history(
        self,
        scope: RepositoryScope,
        *,
        after_checkpoint_id: UUID,
        storage_namespace: str,
        session: AsyncSession | None = None,
    ) -> list[CheckpointRecord]:
        """Only a confirmed current publication can trigger automatic pruning.

        The repository lock is shared with publication and restore admission.
        Retired identities cannot publish again or acquire a new restore pin.
        Keep their ledger rows for unknown delete ACK recovery and replay safety.
        """
        session = require_session(session)
        if not isinstance(after_checkpoint_id, UUID):
            raise ValueError("invalid_checkpoint_retention_trigger")
        if not await _lock_owner(session, scope):
            return []
        params = {
            **scope.params(),
            "checkpoint_id": after_checkpoint_id,
            "keep": RETAINED_CHECKPOINTS,
            "storage_namespace": storage_namespace,
        }
        confirmed = await session.scalar(
            text(
                "SELECT 1 FROM profile.ide_checkpoint_intent c "
                "WHERE c.repository_id=:repository_id "
                "AND c.checkpoint_id=:checkpoint_id AND c.state='published' "
                "AND c.thread_id=:thread_id AND c.user_id=:user_id"
            ),
            params,
        )
        if confirmed is None:
            return []
        await session.execute(
            text(
                "WITH retained AS (SELECT c.checkpoint_id FROM profile.ide_checkpoint_intent c "
                "LEFT JOIN profile.ide_repository_head head ON head.repository_id=c.repository_id "
                "WHERE c.repository_id=:repository_id AND c.thread_id=:thread_id "
                "AND c.user_id=:user_id AND c.state='published' "
                "ORDER BY (c.checkpoint_id=head.checkpoint_id) DESC NULLS LAST, "
                "c.published_at DESC,c.checkpoint_id DESC LIMIT :keep) "
                "UPDATE profile.ide_checkpoint_intent c SET state='retired',published_at=NULL,"
                "updated_at=clock_timestamp() WHERE c.repository_id=:repository_id "
                "AND c.thread_id=:thread_id AND c.user_id=:user_id AND c.state='published' "
                "AND c.command_pins=0 "
                "AND NOT EXISTS (SELECT 1 FROM profile.ide_repository_head head "
                "WHERE head.repository_id=c.repository_id AND head.checkpoint_id=c.checkpoint_id) "
                "AND NOT EXISTS (SELECT 1 FROM retained k WHERE k.checkpoint_id=c.checkpoint_id) "
                "AND NOT EXISTS (SELECT 1 FROM profile.ide_restore_intent i "
                "WHERE i.repository_id=c.repository_id AND i.active_checkpoint_id=c.checkpoint_id)"
            ),
            params,
        )
        # Bounded retry batch also includes earlier retired uploads. Never drop
        # a ledger reference when deletion fails or its acknowledgement is lost.
        return await self._pending_cleanup(session, scope, storage_namespace)

    @connection()
    async def acknowledge_discard(
        self, intent: CheckpointIntent, *, session: AsyncSession | None = None
    ) -> bool:
        """Release accounting only after a settled upload and exact delete ACK.

        The row remains a tombstone, not proof of object absence. Repeating a
        delete after lost ACK is safe and does not resurrect the snapshot ID.
        """
        session = require_session(session)
        if not await _lock_owner(session, intent.blob.scope):
            return False
        result = await session.execute(
            text(
                "UPDATE profile.ide_checkpoint_intent c SET collected_at=clock_timestamp(),"
                "updated_at=clock_timestamp() "
                "WHERE c.repository_id=:repository_id AND c.thread_id=:thread_id "
                "AND c.user_id=:user_id AND c.checkpoint_id=:checkpoint_id "
                "AND c.state IN ('retired','conflict') AND c.sha256=:sha256 AND c.size=:size "
                "AND c.command_pins=0 "
                "AND c.upload_settled_at IS NOT NULL AND c.collected_at IS NULL "
                "AND c.allocation_id=:allocation_id "
                "AND c.base_checkpoint_id IS NOT DISTINCT FROM :base_checkpoint_id "
                "AND c.storage_namespace=:storage_namespace "
                "AND NOT EXISTS (SELECT 1 FROM profile.ide_repository_head h "
                "WHERE h.repository_id=c.repository_id AND h.checkpoint_id=c.checkpoint_id) "
                "AND NOT EXISTS (SELECT 1 FROM profile.ide_restore_intent i "
                "WHERE i.repository_id=c.repository_id AND i.active_checkpoint_id=c.checkpoint_id) "
                "RETURNING c.checkpoint_id"
            ),
            intent.params(),
        )
        return result.first() is not None
