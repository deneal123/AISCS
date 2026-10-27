"""Short owned transactions; neither allocation nor Git runs under a DB lock."""

from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.ide.repositories import IdeRepositoryRepository
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

_NAMESPACE = UUID("6f536190-7564-4663-a9ab-c0708537be78")
_OWNED = (
    "FROM profile.ide_clone_intent c "
    "JOIN profile.ide_repository r ON r.repository_id=c.repository_id "
    "JOIN profile.ide_repository s ON s.repository_id=c.source_repository_id "
    "JOIN profile.chat_threads t ON t.thread_id=c.thread_id "
    "WHERE c.user_id=:user_id AND c.thread_id=:thread_id "
    "AND r.user_id=c.user_id AND r.thread_id=c.thread_id "
    "AND s.user_id=c.user_id AND s.thread_id=c.thread_id AND t.user_id=c.user_id"
)
_COLUMNS = (
    "SELECT c.intent_id,c.origin,c.branch,c.request_digest,c.state,c.started_at,"
    "c.code,c.source_repository_id,r.repository_id,r.name,r.created_at "
)
_READ = f"{_COLUMNS}{_OWNED} AND c.intent_id=:intent_id"


class IdeCloneRepository(BaseRepository):
    @connection()
    async def latest_owned(
        self,
        scope: RepositoryScope,
        *,
        session: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        result = await require_session(session).execute(
            text(
                f"{_COLUMNS}{_OWNED} AND (c.repository_id=:repository_id "
                "OR c.source_repository_id=:repository_id) "
                "ORDER BY c.created_at DESC NULLS LAST,c.intent_id DESC LIMIT 1"
            ),
            scope.params(),
        )
        row = result.mappings().first()
        return dict(row) if row else None

    @connection()
    async def get_owned(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        intent_id: UUID,
        session: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        result = await require_session(session).execute(
            text(_READ),
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "intent_id": intent_id,
            },
        )
        row = result.mappings().first()
        return dict(row) if row else None

    @connection()
    async def reserve(
        self,
        source: RepositoryScope,
        *,
        intent_id: UUID,
        request_digest: str,
        name: str,
        origin: str | None = None,
        branch: str | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        session = require_session(session)
        params = {**source.params(), "intent_id": intent_id}
        owner = await session.execute(
            text(
                "SELECT thread_id FROM profile.chat_threads WHERE thread_id=:thread_id "
                "AND user_id=:user_id FOR UPDATE"
            ),
            params,
        )
        repositories = IdeRepositoryRepository(self.connector)
        if (
            owner.first() is None
            or await repositories.get_owned(**source.params(), session=session) is None
        ):
            return None
        lookup = {"thread_id": source.thread_id, "user_id": source.user_id, "intent_id": intent_id}
        existing = await self.get_owned(**lookup, session=session)
        if existing:
            if (
                existing["request_digest"] == request_digest
                and existing["origin"] is None
                and origin
            ):
                # Only a verified replay can supply legacy missing parameters.
                await session.execute(
                    text(
                        "UPDATE profile.ide_clone_intent SET origin=:origin,branch=:branch "
                        "WHERE user_id=:user_id AND thread_id=:thread_id AND intent_id=:intent_id "
                        "AND request_digest=:digest AND origin IS NULL"
                    ),
                    {**lookup, "origin": origin, "branch": branch, "digest": request_digest},
                )
                existing = await self.get_owned(**lookup, session=session)
            return existing
        # Different purpose namespace from public descriptor registration. A
        # pre-existing colliding descriptor must never be used as a destination.
        inserted = await session.execute(
            text(
                "INSERT INTO profile.ide_repository "
                "(repository_id,thread_id,user_id,creation_intent_id,name) VALUES "
                "(:destination_id,:thread_id,:user_id,:creation_id,:name) "
                "ON CONFLICT (user_id,thread_id,creation_intent_id) DO NOTHING "
                "RETURNING repository_id"
            ),
            {
                **params,
                "destination_id": uuid4(),
                "creation_id": uuid5(_NAMESPACE, str(intent_id)),
                "name": name,
            },
        )
        destination = inserted.scalar_one_or_none()
        if destination is None:
            return {"conflict": True}
        await session.execute(
            text(
                "INSERT INTO profile.ide_clone_intent "
                "(intent_id,user_id,thread_id,source_repository_id,repository_id,"
                "request_digest,origin,branch) VALUES (:intent_id,:user_id,:thread_id,"
                ":source_id,:destination_id,:digest,:origin,:branch)"
            ),
            {
                **params,
                "source_id": source.repository_id,
                "destination_id": destination,
                "digest": request_digest,
                "origin": origin,
                "branch": branch,
            },
        )
        return await self.get_owned(**lookup, session=session)

    @connection()
    async def claim(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        intent_id: UUID,
        session: AsyncSession | None = None,
    ) -> bool:
        result = await require_session(session).execute(
            text(
                "UPDATE profile.ide_clone_intent j SET state='cloning',"
                "started_at=floor(extract(epoch FROM clock_timestamp()))::bigint "
                "WHERE j.user_id=:user_id AND j.thread_id=:thread_id AND j.intent_id=:intent_id "
                f"AND j.state='reserved' AND EXISTS (SELECT 1 {_OWNED} AND c.intent_id=:intent_id) "
                "RETURNING j.intent_id"
            ),
            {"thread_id": thread_id, "user_id": user_id, "intent_id": intent_id},
        )
        return result.first() is not None

    @connection()
    async def finish(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        intent_id: UUID,
        state: str,
        code: str | None,
        session: AsyncSession | None = None,
    ) -> None:
        if state not in {"complete", "failed", "unconfirmed"}:
            raise ValueError("invalid_clone_state")
        await require_session(session).execute(
            text(
                "UPDATE profile.ide_clone_intent j SET state=:state,code=:code "
                "WHERE j.user_id=:user_id AND j.thread_id=:thread_id AND j.intent_id=:intent_id "
                f"AND j.state='cloning' AND EXISTS (SELECT 1 {_OWNED} AND c.intent_id=:intent_id)"
            ),
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "intent_id": intent_id,
                "state": state,
                "code": code,
            },
        )
