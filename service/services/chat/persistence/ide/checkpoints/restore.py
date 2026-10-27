"""Commit-before-upload restore claims and atomic expired-generation replacement.

No token, body, network call, policy choice or cleanup belongs in these locks.
This private foundation is deliberately not exposed as a user restore action.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.chat.domain.ide.checkpoints.restore import RestoreRecord, RestoreReservation
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.harness.commands.gate import project_is_busy
from service.services.chat.persistence.ide.checkpoints.repository import _lock_owner
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

_OWNED = (
    "FROM profile.ide_repository r JOIN profile.chat_threads t ON t.thread_id=r.thread_id "
    "WHERE r.repository_id=:repository_id AND r.thread_id=:thread_id "
    "AND r.user_id=:user_id AND t.user_id=:user_id"
)
_READ = (
    "SELECT i.* FROM profile.ide_restore_intent i WHERE i.repository_id=:repository_id "
    "AND i.restore_id=:restore_id AND i.thread_id=:thread_id AND i.user_id=:user_id "
    f"AND EXISTS (SELECT 1 {_OWNED})"
)


async def _read(
    session: AsyncSession, scope: RepositoryScope, restore_id: UUID
) -> RestoreRecord | None:
    row = await session.execute(text(_READ), {**scope.params(), "restore_id": restore_id})
    return RestoreRecord.from_row(row.mappings().first())


class IdeRestoreRepository(BaseRepository):
    @connection()
    async def latest_owned(
        self, scope: RepositoryScope, *, session: AsyncSession | None = None
    ) -> RestoreRecord | None:
        result = await require_session(session).execute(
            text(
                "SELECT i.* FROM profile.ide_restore_intent i WHERE i.repository_id=:repository_id "
                "AND i.thread_id=:thread_id AND i.user_id=:user_id "
                f"AND EXISTS (SELECT 1 {_OWNED}) "
                "ORDER BY i.created_at DESC,i.restore_id DESC LIMIT 1"
            ),
            scope.params(),
        )
        return RestoreRecord.from_row(result.mappings().first())

    @connection()
    async def get_owned(
        self, scope: RepositoryScope, restore_id: UUID, *, session: AsyncSession | None = None
    ) -> RestoreRecord | None:
        return await _read(require_session(session), scope, restore_id)

    @connection()
    async def reserve(
        self,
        scope: RepositoryScope,
        restore_id: UUID,
        checkpoint_id: UUID,
        base_allocation_id: UUID,
        *,
        ttl_sec: int,
        session: AsyncSession | None = None,
    ) -> RestoreReservation:
        session = require_session(session)
        if (
            type(ttl_sec) is not int
            or not 1 <= ttl_sec <= 2**31 - 1
            or not all(
                isinstance(value, UUID) for value in (restore_id, checkpoint_id, base_allocation_id)
            )
        ):
            raise ValueError("invalid_restore_claim")
        if not await _lock_owner(session, scope):
            return RestoreReservation(failure="missing")
        if await project_is_busy(session, scope.repository_id):
            return RestoreReservation(failure="command_busy")
        existing = await _read(session, scope, restore_id)
        if existing is not None:
            return RestoreReservation(existing)
        # Lock the old runtime, but never replace it on dispatch. Ordinary
        # readers/agent resolution cannot discover the new allocation early.
        runtime = await session.execute(
            text(
                "SELECT allocation_id,expires_at<=extract(epoch FROM clock_timestamp()) AS expired "
                "FROM profile.ide_repository_runtime WHERE repository_id=:repository_id FOR UPDATE"
            ),
            scope.params(),
        )
        old = runtime.mappings().first()
        if old is None or old["allocation_id"] != base_allocation_id or not old["expired"]:
            return RestoreReservation(failure="runtime_not_expired")
        checkpoint = await session.execute(
            text(
                "SELECT sha256,size,storage_namespace FROM profile.ide_checkpoint_intent "
                "WHERE repository_id=:repository_id AND checkpoint_id=:checkpoint_id "
                "AND thread_id=:thread_id AND user_id=:user_id AND state='published' FOR SHARE"
            ),
            {**scope.params(), "checkpoint_id": checkpoint_id},
        )
        saved = checkpoint.mappings().first()
        if saved is None:
            return RestoreReservation(failure="checkpoint_not_published")
        # A *new explicit intent* may replace an already expired pending claim,
        # never one whose upload could still materialize a live allocation.
        await session.execute(
            text(
                "UPDATE profile.ide_restore_intent SET state='expired',active_checkpoint_id=NULL,"
                "updated_at=clock_timestamp() "
                "WHERE repository_id=:repository_id AND state='pending' "
                "AND expires_at<=extract(epoch FROM clock_timestamp())"
            ),
            scope.params(),
        )
        if await session.scalar(
            text(
                "SELECT 1 FROM profile.ide_restore_intent WHERE repository_id=:repository_id "
                "AND state='pending'"
            ),
            scope.params(),
        ):
            return RestoreReservation(failure="restore_pending")
        await session.execute(
            text(
                "INSERT INTO profile.ide_restore_intent "
                "(repository_id,restore_id,thread_id,user_id,checkpoint_id,active_checkpoint_id,"
                "base_allocation_id,"
                "allocation_id,expires_at,sha256,size,storage_namespace) "
                "VALUES (:repository_id,:restore_id,:thread_id,:user_id,:checkpoint_id,"
                ":checkpoint_id,"
                ":base_allocation_id,:allocation_id,"
                "floor(extract(epoch FROM clock_timestamp()))::bigint+:ttl_sec,"
                ":sha256,:size,:storage_namespace)"
            ),
            {
                **scope.params(),
                **dict(saved),
                "restore_id": restore_id,
                "checkpoint_id": checkpoint_id,
                "base_allocation_id": base_allocation_id,
                "allocation_id": uuid4(),
                "ttl_sec": ttl_sec,
            },
        )
        return RestoreReservation(await _read(session, scope, restore_id), True)

    @connection()
    async def publish(
        self,
        scope: RepositoryScope,
        restore_id: UUID,
        *,
        verified: bool = False,
        session: AsyncSession | None = None,
    ) -> RestoreRecord | None:
        session = require_session(session)
        if not await _lock_owner(session, scope):
            return None
        record = await _read(session, scope, restore_id)
        if record is None or record.state != "pending":
            return record
        params = {
            **scope.params(),
            "restore_id": restore_id,
            "allocation_id": record.allocation_id,
            "base_allocation_id": record.base_allocation_id,
            "expires_at": record.expires_at,
        }
        # Recheck expiry under the runtime row lock before the atomic swap.
        result = await session.execute(
            text(
                "SELECT allocation_id,expires_at<=extract(epoch FROM clock_timestamp()) AS expired,"
                ":expires_at>extract(epoch FROM clock_timestamp()) AS target_alive "
                "FROM profile.ide_repository_runtime WHERE repository_id=:repository_id FOR UPDATE"
            ),
            params,
        )
        old = result.mappings().first()
        state = "expired" if old is not None and not old["target_alive"] else "conflict"
        if (
            old is not None
            and old["allocation_id"] == record.base_allocation_id
            and old["expired"]
            and old["target_alive"]
        ):
            if verified is not True:
                return record
            result = await session.execute(
                text(
                    "UPDATE profile.ide_repository_runtime SET allocation_id=:allocation_id,"
                    "expires_at=:expires_at,state='ready',retry_allowed=false,observation=observation+1,"
                    "updated_at=clock_timestamp() WHERE repository_id=:repository_id "
                    "AND allocation_id=:base_allocation_id "
                    "AND expires_at<=extract(epoch FROM clock_timestamp()) "
                    "AND :expires_at>extract(epoch FROM clock_timestamp()) RETURNING allocation_id"
                ),
                params,
            )
            state = "published" if result.first() is not None else "expired"
        await session.execute(
            text(
                "UPDATE profile.ide_restore_intent SET state=:state,active_checkpoint_id=NULL,"
                "updated_at=clock_timestamp() "
                "WHERE repository_id=:repository_id AND restore_id=:restore_id AND state='pending'"
            ),
            {**params, "state": state},
        )
        return await _read(session, scope, restore_id)
