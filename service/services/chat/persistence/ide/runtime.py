"""Durable dispatch claim and fenced observations. Never persist credentials."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.chat.domain.ide.runtime import (
    RUNTIME_STATES,
    RepositoryScope,
    RuntimeAttempt,
    RuntimeState,
)
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

_OWNED = (
    "FROM profile.ide_repository r JOIN profile.chat_threads t ON t.thread_id=r.thread_id "
    "WHERE r.repository_id=:repository_id AND r.thread_id=:thread_id "
    "AND r.user_id=:user_id AND t.user_id=:user_id"
)
_COLUMNS = "w.allocation_id,w.expires_at,w.state,w.observation,w.retry_allowed"
_RETURNED = "allocation_id,expires_at,state,observation,retry_allowed"
_READ = (
    f"SELECT {_COLUMNS} FROM profile.ide_repository_runtime w "
    f"WHERE w.repository_id=:repository_id AND EXISTS (SELECT 1 {_OWNED})"
)


class IdeRuntimeRepository(BaseRepository):
    @connection()
    async def get_owned(
        self, scope: RepositoryScope, *, session: AsyncSession | None = None
    ) -> RuntimeAttempt | None:
        session = require_session(session)
        result = await session.execute(text(_READ), scope.params())
        return RuntimeAttempt.from_row(result.mappings().first())

    @connection()
    async def claim(
        self,
        scope: RepositoryScope,
        *,
        ttl_sec: int,
        allow_retry: bool = True,
        session: AsyncSession | None = None,
    ) -> tuple[RuntimeAttempt | None, bool]:
        session = require_session(session)
        if type(ttl_sec) is not int or not 1 <= ttl_sec <= 2**31 - 1:
            raise ValueError("invalid_runtime_ttl")
        result = await session.execute(
            text(
                "INSERT INTO profile.ide_repository_runtime "
                "(repository_id,allocation_id,expires_at,state,observation) "
                "SELECT r.repository_id,:allocation_id,"
                "floor(extract(epoch FROM clock_timestamp()))::bigint + :ttl_sec,'dispatching',0 "
                f"{_OWNED} ON CONFLICT (repository_id) DO NOTHING "
                f"RETURNING {_RETURNED}"
            ),
            {**scope.params(), "allocation_id": uuid4(), "ttl_sec": ttl_sec},
        )
        created = RuntimeAttempt.from_row(result.mappings().first())
        if created is not None:
            return created, True
        if not allow_retry:
            # Entry/replay must not turn a concurrent quota denial into another
            # dispatch. Only the explicit provision action may rearm rejection.
            result = await session.execute(text(_READ), scope.params())
            return RuntimeAttempt.from_row(result.mappings().first()), False
        # Only an explicit provision action may rearm a confirmed pre-allocation
        # quota rejection. Ambiguous outcomes can never enter this branch.
        result = await session.execute(
            text(
                "UPDATE profile.ide_repository_runtime w SET state='dispatching',"
                "retry_allowed=false,observation=observation+1,updated_at=now() "
                "WHERE w.repository_id=:repository_id AND w.state='rejected' AND w.retry_allowed "
                "AND w.expires_at>extract(epoch FROM clock_timestamp()) "
                f"AND EXISTS (SELECT 1 {_OWNED}) RETURNING {_COLUMNS}"
            ),
            scope.params(),
        )
        rearmed = RuntimeAttempt.from_row(result.mappings().first())
        if rearmed is not None:
            return rearmed, True
        result = await session.execute(text(_READ), scope.params())
        return RuntimeAttempt.from_row(result.mappings().first()), False

    @connection()
    async def begin_observation(
        self,
        scope: RepositoryScope,
        attempt: RuntimeAttempt,
        *,
        session: AsyncSession | None = None,
    ) -> RuntimeAttempt | None:
        session = require_session(session)
        result = await session.execute(
            text(
                "UPDATE profile.ide_repository_runtime w SET observation=observation+1 "
                "WHERE w.repository_id=:repository_id AND w.allocation_id=:allocation_id "
                f"AND EXISTS (SELECT 1 {_OWNED}) RETURNING {_COLUMNS}"
            ),
            {**scope.params(), "allocation_id": attempt.allocation_id},
        )
        return RuntimeAttempt.from_row(result.mappings().first())

    @connection()
    async def record_observation(
        self,
        scope: RepositoryScope,
        attempt: RuntimeAttempt,
        state: RuntimeState,
        *,
        retry_allowed: bool = False,
        session: AsyncSession | None = None,
    ) -> RuntimeAttempt | None:
        session = require_session(session)
        if state not in RUNTIME_STATES or retry_allowed and state != "rejected":
            raise ValueError("invalid_runtime_state")
        result = await session.execute(
            text(
                "UPDATE profile.ide_repository_runtime w SET state=:state,"
                "retry_allowed=:retry_allowed,updated_at=now() "
                "WHERE w.repository_id=:repository_id AND w.allocation_id=:allocation_id "
                "AND w.observation=:observation "
                f"AND EXISTS (SELECT 1 {_OWNED}) RETURNING {_COLUMNS}"
            ),
            {
                **scope.params(),
                "allocation_id": attempt.allocation_id,
                "observation": attempt.observation,
                "state": state,
                "retry_allowed": retry_allowed,
            },
        )
        updated = RuntimeAttempt.from_row(result.mappings().first())
        if updated is not None:
            return updated
        # A later observation owns state; an old response cannot downgrade it.
        result = await session.execute(text(_READ), scope.params())
        return RuntimeAttempt.from_row(result.mappings().first())
