"""Short, owner-serialized first-entry claim, committed before network dispatch."""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.chat.domain.documents.preparation import PdfPreparation, PdfPreparationScope
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

_COLUMNS = "p.allocation_id,p.workspace_id,p.expires_at,p.scaffold_state"
_OWNED = (
    "FROM profile.pdf_preparation p JOIN profile.chat_threads t ON t.thread_id=p.thread_id "
    "WHERE p.thread_id=:thread_id AND p.user_id=:user_id AND t.user_id=:user_id"
)


class PdfPreparationRepository(BaseRepository):
    @connection()
    async def claim_scaffold(
        self,
        scope: PdfPreparationScope,
        *,
        allow_retry: bool = False,
        session: AsyncSession | None = None,
    ) -> bool:
        result = await require_session(session).execute(
            text(
                "UPDATE profile.pdf_preparation p SET scaffold_state='dispatching' "
                "WHERE p.thread_id=:thread_id AND p.user_id=:user_id "
                "AND p.expires_at>extract(epoch FROM clock_timestamp()) "
                "AND (p.scaffold_state='idle' OR (:allow_retry AND p.scaffold_state='rejected')) "
                "AND EXISTS (SELECT 1 FROM profile.chat_threads t "
                "WHERE t.thread_id=p.thread_id AND t.user_id=:user_id) RETURNING p.thread_id"
            ),
            {**scope.params(), "allow_retry": allow_retry},
        )
        return result.first() is not None

    @connection()
    async def reject_scaffold(
        self,
        scope: PdfPreparationScope,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        await require_session(session).execute(
            text(
                "UPDATE profile.pdf_preparation p SET scaffold_state='rejected' "
                "WHERE p.thread_id=:thread_id AND p.user_id=:user_id "
                "AND p.scaffold_state='dispatching' "
                "AND EXISTS (SELECT 1 FROM profile.chat_threads t "
                "WHERE t.thread_id=p.thread_id AND t.user_id=:user_id)"
            ),
            scope.params(),
        )

    @connection()
    async def observe_project(
        self,
        scope: PdfPreparationScope,
        *,
        session: AsyncSession | None = None,
    ) -> bool:
        result = await require_session(session).execute(
            text(
                "UPDATE profile.pdf_preparation p SET scaffold_state='observed' "
                "WHERE p.thread_id=:thread_id AND p.user_id=:user_id "
                "AND p.expires_at>extract(epoch FROM clock_timestamp()) "
                "AND EXISTS (SELECT 1 FROM profile.chat_threads t "
                "WHERE t.thread_id=p.thread_id AND t.user_id=:user_id) RETURNING p.thread_id"
            ),
            scope.params(),
        )
        return result.first() is not None

    @connection()
    async def ensure_owner(
        self, scope: PdfPreparationScope, *, session: AsyncSession | None = None
    ) -> bool:
        session = require_session(session)
        await session.execute(
            text(
                "INSERT INTO profile.chat_threads (thread_id,user_id,title,created_at,updated_at) "
                "VALUES (:thread_id,:user_id,'Новый документ',now(),now()) "
                "ON CONFLICT (thread_id) DO NOTHING"
            ),
            scope.params(),
        )
        result = await session.execute(
            text(
                "SELECT thread_id FROM profile.chat_threads "
                "WHERE thread_id=:thread_id AND user_id=:user_id"
            ),
            scope.params(),
        )
        return result.first() is not None

    @connection()
    async def get_owned(
        self, scope: PdfPreparationScope, *, session: AsyncSession | None = None
    ) -> PdfPreparation | None:
        result = await require_session(session).execute(
            text(f"SELECT {_COLUMNS} {_OWNED}"), scope.params()
        )
        row = result.mappings().first()
        return PdfPreparation(**row) if row is not None else None

    @connection()
    async def claim(
        self,
        scope: PdfPreparationScope,
        *,
        ttl_sec: int,
        workspace_id: str | None = None,
        expires_at: int | None = None,
        session: AsyncSession | None = None,
    ) -> tuple[PdfPreparation | None, bool]:
        if type(ttl_sec) is not int or not 1 <= ttl_sec <= 2**31 - 1:
            raise ValueError("invalid_pdf_preparation_ttl")
        if (workspace_id is None) != (expires_at is None):
            raise ValueError("invalid_pdf_preparation_binding")
        session = require_session(session)
        owner = await session.execute(
            text(
                "SELECT thread_id FROM profile.chat_threads "
                "WHERE thread_id=:thread_id AND user_id=:user_id FOR UPDATE"
            ),
            scope.params(),
        )
        if owner.first() is None:
            return None, False
        result = await session.execute(text(f"SELECT {_COLUMNS} {_OWNED}"), scope.params())
        row = result.mappings().first()
        if row is not None:
            return PdfPreparation(**row), False
        result = await session.execute(
            text(
                "INSERT INTO profile.pdf_preparation "
                "(thread_id,user_id,allocation_id,workspace_id,expires_at) "
                "VALUES (:thread_id,:user_id,:allocation_id,:workspace_id,"
                "coalesce(:expires_at,"
                "floor(extract(epoch FROM clock_timestamp()))::bigint+:ttl_sec)) "
                "RETURNING allocation_id,workspace_id,expires_at,scaffold_state"
            ),
            {
                **scope.params(),
                "allocation_id": None if workspace_id else uuid4(),
                "workspace_id": workspace_id,
                "expires_at": expires_at,
                "ttl_sec": ttl_sec,
            },
        )
        row = result.mappings().one()
        return PdfPreparation(**row), workspace_id is None
