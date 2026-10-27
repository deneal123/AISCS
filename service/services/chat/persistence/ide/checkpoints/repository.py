"""Short owned transactions; no object storage calls inside database locks."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.chat.domain.ide.checkpoints.budget import CheckpointStorageBudget
from service.services.chat.domain.ide.checkpoints.revision import (
    CheckpointIntent,
    CheckpointRecord,
    CheckpointReservation,
    CheckpointState,
)
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

_OWNED = (
    "FROM profile.ide_repository r JOIN profile.chat_threads t ON t.thread_id=r.thread_id "
    "WHERE r.repository_id=:repository_id AND r.thread_id=:thread_id "
    "AND r.user_id=:user_id AND t.user_id=:user_id"
)
_READ = (
    "SELECT c.*,h.checkpoint_id AS current_checkpoint_id FROM profile.ide_checkpoint_intent c "
    "LEFT JOIN profile.ide_repository_head h ON h.repository_id=c.repository_id "
    "WHERE c.repository_id=:repository_id AND c.checkpoint_id=:checkpoint_id "
    "AND c.thread_id=:thread_id AND c.user_id=:user_id "
    f"AND EXISTS (SELECT 1 {_OWNED})"
)


async def _lock_owner(session: AsyncSession, scope: RepositoryScope) -> bool:
    result = await session.execute(
        text(f"SELECT r.repository_id {_OWNED} FOR UPDATE OF r FOR SHARE OF t"), scope.params()
    )
    return result.first() is not None


async def _read(
    session: AsyncSession, scope: RepositoryScope, checkpoint_id: UUID
) -> CheckpointRecord | None:
    result = await session.execute(text(_READ), {**scope.params(), "checkpoint_id": checkpoint_id})
    return CheckpointRecord.from_row(result.mappings().first())


async def _runtime(session: AsyncSession, scope: RepositoryScope) -> Mapping[str, Any] | None:
    result = await session.execute(
        text(
            "SELECT allocation_id,state,expires_at>extract(epoch FROM clock_timestamp()) AS alive "
            "FROM profile.ide_repository_runtime WHERE repository_id=:repository_id FOR SHARE"
        ),
        scope.params(),
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


class IdeCheckpointRepository(BaseRepository):
    @connection()
    async def inventory(
        self, scope: RepositoryScope, *, session: AsyncSession | None = None
    ) -> list[dict[str, Any]] | None:
        session = require_session(session)
        owner = await session.execute(text(f"SELECT r.repository_id {_OWNED}"), scope.params())
        if owner.first() is None:
            return None
        result = await session.execute(
            text(
                "SELECT c.checkpoint_id,c.state,c.size,c.created_at,c.published_at,"
                "c.upload_settled_at,"
                "h.checkpoint_id AS current_checkpoint_id FROM profile.ide_checkpoint_intent c "
                "LEFT JOIN profile.ide_repository_head h ON h.repository_id=c.repository_id "
                "WHERE c.repository_id=:repository_id AND c.thread_id=:thread_id "
                "AND c.user_id=:user_id "
                "AND c.state IN ('published','pending','retired','conflict') "
                "AND c.collected_at IS NULL "
                f"AND EXISTS (SELECT 1 {_OWNED}) "
                "ORDER BY (c.checkpoint_id=h.checkpoint_id) DESC NULLS LAST,"
                "c.created_at DESC,c.checkpoint_id DESC LIMIT 33"
            ),
            scope.params(),
        )
        return [dict(row) for row in result.mappings().all()]

    @connection()
    async def accounted_bytes(self, user_id: UUID, *, session: AsyncSession | None = None) -> int:
        result = await require_session(session).scalar(
            text(
                "SELECT coalesce(sum(size),0) FROM profile.ide_checkpoint_intent "
                "WHERE user_id=:user_id AND collected_at IS NULL"
            ),
            {"user_id": user_id},
        )
        return int(result or 0)

    @connection()
    async def abandon_pending(
        self,
        scope: RepositoryScope,
        checkpoint_id: UUID,
        *,
        session: AsyncSession | None = None,
    ) -> tuple[CheckpointRecord | None, bool]:
        """Retire before physical discard; an unknown uploader stays protected."""
        return await self._retire_unpublished(
            require_session(session), scope, checkpoint_id, require_settled=True
        )

    @connection()
    async def revoke_pending(
        self,
        scope: RepositoryScope,
        checkpoint_id: UUID,
        *,
        session: AsyncSession | None = None,
    ) -> tuple[CheckpointRecord | None, bool]:
        """Revoke publication only. Never settle a writer, collect or release quota."""
        return await self._retire_unpublished(
            require_session(session), scope, checkpoint_id, require_settled=False
        )

    async def _retire_unpublished(
        self,
        session: AsyncSession,
        scope: RepositoryScope,
        checkpoint_id: UUID,
        *,
        require_settled: bool,
    ) -> tuple[CheckpointRecord | None, bool]:
        if not await _lock_owner(session, scope):
            return None, False
        record = await _read(session, scope, checkpoint_id)
        if (
            record is None
            or record.state == "published"
            or (require_settled and not record.upload_settled)
            or record.current_checkpoint_id == checkpoint_id
        ):
            return record, False
        pinned = await session.scalar(
            text(
                "SELECT 1 FROM profile.ide_restore_intent WHERE repository_id=:repository_id "
                "AND active_checkpoint_id=:checkpoint_id LIMIT 1"
            ),
            {**scope.params(), "checkpoint_id": checkpoint_id},
        )
        if pinned is not None:
            return record, False
        if record.state == "pending":
            record = await self._terminal(session, record, "retired")
        return record, record is not None

    @connection()
    async def get_owned(
        self, scope: RepositoryScope, checkpoint_id: UUID, *, session: AsyncSession | None = None
    ) -> CheckpointRecord | None:
        return await _read(require_session(session), scope, checkpoint_id)

    @connection()
    async def head(
        self, scope: RepositoryScope, *, session: AsyncSession | None = None
    ) -> CheckpointRecord | None:
        session = require_session(session)
        result = await session.execute(
            text(
                "SELECT c.*,h.checkpoint_id AS current_checkpoint_id "
                "FROM profile.ide_repository_head h JOIN profile.ide_checkpoint_intent c "
                "ON c.repository_id=h.repository_id AND c.checkpoint_id=h.checkpoint_id "
                "WHERE h.repository_id=:repository_id AND c.thread_id=:thread_id "
                f"AND c.user_id=:user_id AND c.state='published' AND EXISTS (SELECT 1 {_OWNED})"
            ),
            scope.params(),
        )
        return CheckpointRecord.from_row(result.mappings().first())

    @connection()
    async def reserve(
        self,
        intent: CheckpointIntent,
        *,
        budget: CheckpointStorageBudget | None = None,
        session: AsyncSession | None = None,
    ) -> CheckpointReservation:
        session = require_session(session)
        scope, checkpoint_id = intent.blob.scope, intent.blob.checkpoint_id
        if budget is not None:
            # Only this per-user budget owner admits additional accounted bytes.
            # Do not lock profile.user and couple snapshot I/O to billing locks.
            lock_id = int.from_bytes(
                hashlib.sha256(b"gpthub:ide-checkpoint-budget:v1|" + scope.user_id.bytes).digest()[
                    :8
                ],
                "big",
                signed=True,
            )
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:budget_lock)"), {"budget_lock": lock_id}
            )
        if not await _lock_owner(session, scope):
            return CheckpointReservation(failure="missing")
        existing = await _read(session, scope, checkpoint_id)
        if existing is not None:
            return CheckpointReservation(existing)
        if budget is not None:
            used = await session.scalar(
                text(
                    "SELECT coalesce(sum(size),0) FROM profile.ide_checkpoint_intent "
                    "WHERE user_id=:user_id AND collected_at IS NULL"
                ),
                scope.params(),
            )
            if (
                intent.blob.size > budget.max_checkpoint_bytes
                or int(used or 0) + intent.blob.size > budget.max_user_bytes
            ):
                return CheckpointReservation(failure="quota")
            pending = await session.scalar(
                text(
                    "SELECT count(*) FROM profile.ide_checkpoint_intent "
                    "WHERE repository_id=:repository_id AND collected_at IS NULL AND "
                    "(state='pending' OR (state IN ('retired','conflict') "
                    "AND upload_settled_at IS NULL))"
                ),
                scope.params(),
            )
            if int(pending or 0) >= budget.max_pending_per_repository:
                return CheckpointReservation(failure="pending")
        runtime = await _runtime(session, scope)
        if (
            runtime is None
            or not runtime["alive"]
            or runtime["state"] != "ready"
            or runtime["allocation_id"] != intent.allocation_id
        ):
            return CheckpointReservation(failure="runtime_not_ready")
        await session.execute(
            text(
                "INSERT INTO profile.ide_repository_head (repository_id) VALUES (:repository_id) "
                "ON CONFLICT (repository_id) DO NOTHING"
            ),
            scope.params(),
        )
        current = await session.scalar(
            text(
                "SELECT checkpoint_id FROM profile.ide_repository_head "
                "WHERE repository_id=:repository_id"
            ),
            scope.params(),
        )
        state = "pending" if current == intent.base_checkpoint_id else "conflict"
        if budget is not None and state == "conflict":
            return CheckpointReservation(failure="head_changed")
        await session.execute(
            text(
                "INSERT INTO profile.ide_checkpoint_intent "
                "(repository_id,checkpoint_id,thread_id,user_id,allocation_id,"
                "base_checkpoint_id,sha256,size,storage_namespace,state) "
                "VALUES (:repository_id,:checkpoint_id,:thread_id,:user_id,:allocation_id,"
                ":base_checkpoint_id,:sha256,:size,:storage_namespace,:state)"
            ),
            {**intent.params(), "state": state},
        )
        return CheckpointReservation(await _read(session, scope, checkpoint_id), state == "pending")

    @connection()
    async def mark_upload_settled(
        self, intent: CheckpointIntent, *, session: AsyncSession | None = None
    ) -> CheckpointRecord | None:
        """Only the uploading owner calls after its exact SDK I/O has settled.

        Reconciliation can verify/publish complete bytes without this receipt,
        but must never invent it or free their storage accounting on that basis.
        """
        session = require_session(session)
        scope = intent.blob.scope
        if not await _lock_owner(session, scope):
            from service.services.chat.persistence.ide.checkpoints.orphans import (
                settle_orphan_upload,
            )

            return await settle_orphan_upload(session, intent)
        await session.execute(
            text(
                "UPDATE profile.ide_checkpoint_intent SET upload_settled_at=coalesce("
                "upload_settled_at,clock_timestamp()) WHERE repository_id=:repository_id "
                "AND checkpoint_id=:checkpoint_id AND thread_id=:thread_id AND user_id=:user_id "
                "AND allocation_id=:allocation_id AND sha256=:sha256 AND size=:size "
                "AND storage_namespace=:storage_namespace "
                "AND base_checkpoint_id IS NOT DISTINCT FROM :base_checkpoint_id "
                "AND collected_at IS NULL"
            ),
            intent.params(),
        )
        return await _read(session, scope, intent.blob.checkpoint_id)

    @connection()
    async def publish(
        self,
        scope: RepositoryScope,
        checkpoint_id: UUID,
        *,
        verified: bool = False,
        historical: bool = False,
        session: AsyncSession | None = None,
    ) -> CheckpointRecord | None:
        """Only the storage-verifying application may opt into head publication.

        Without verification this can retire an obsolete intent, never advance
        HEAD, including if a formerly stale metadata observation is superseded.
        """
        session = require_session(session)
        if not await _lock_owner(session, scope):
            return None
        record = await _read(session, scope, checkpoint_id)
        if record is None or record.state != "pending":
            return record
        # The public Save variant may keep verified bytes as a historical
        # version. This NEVER relaxes allocation/expiry/CAS fences on HEAD.
        keep_history = verified is True and historical is True
        if record.current_checkpoint_id != record.intent.base_checkpoint_id:
            return await self._terminal(
                session, record, "published" if keep_history else "conflict"
            )
        runtime = await _runtime(session, scope)
        if (
            runtime is None
            or runtime["allocation_id"] != record.intent.allocation_id
            or not runtime["alive"]
            or runtime["state"] in {"expired", "rejected"}
        ):
            return await self._terminal(session, record, "published" if keep_history else "retired")
        if runtime["state"] != "ready" or verified is not True:
            if keep_history:
                return await self._terminal(session, record, "published")
            return record
        result = await session.execute(
            text(
                "UPDATE profile.ide_repository_head SET checkpoint_id=:checkpoint_id "
                "WHERE repository_id=:repository_id AND checkpoint_id IS NOT DISTINCT FROM "
                ":base_checkpoint_id AND EXISTS (SELECT 1 FROM profile.ide_repository_runtime w "
                "WHERE w.repository_id=:repository_id AND w.allocation_id=:allocation_id "
                "AND w.state='ready' AND w.expires_at>extract(epoch FROM clock_timestamp())) "
                "RETURNING checkpoint_id"
            ),
            record.intent.params(),
        )
        if result.first() is None:
            # Owner/runtime rows remain locked. A matching base at this point
            # can only have missed the final wall-clock expiry fence.
            return await self._terminal(session, record, "published" if keep_history else "retired")
        return await self._terminal(session, record, "published")

    async def _terminal(
        self, session: AsyncSession, record: CheckpointRecord, state: CheckpointState
    ) -> CheckpointRecord | None:
        await session.execute(
            text(
                "UPDATE profile.ide_checkpoint_intent SET state=:state,"
                "updated_at=clock_timestamp(),"
                "published_at=CASE WHEN :published THEN clock_timestamp() ELSE NULL END "
                "WHERE repository_id=:repository_id AND checkpoint_id=:checkpoint_id "
                "AND state='pending'"
            ),
            {**record.intent.params(), "state": state, "published": state == "published"},
        )
        return await _read(session, record.intent.blob.scope, record.intent.blob.checkpoint_id)
