"""Durable repository identity, never a thread's mutable workspace binding.

Like ChatRepository, these tables use explicit SQL and the existing PgConnector.
An allocation token, remote credential or file body does not belong in this table.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

_COLUMNS = "r.repository_id, r.name, r.created_at"
_OWNED_JOIN = (
    "FROM profile.ide_repository r JOIN profile.chat_threads t ON t.thread_id = r.thread_id "
    "WHERE r.thread_id = :thread_id AND r.user_id = :user_id AND t.user_id = :user_id "
)


class IdeRepositoryRepository(BaseRepository):
    @connection()
    async def clone_dispatch_owned(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        repository_id: UUID,
        intent_id: UUID,
        session: AsyncSession | None = None,
    ) -> bool:
        result = await require_session(session).execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM profile.ide_clone_intent c "
                "JOIN profile.ide_repository s ON s.repository_id=c.source_repository_id "
                "WHERE c.repository_id=r.repository_id AND c.intent_id=:intent_id "
                "AND c.user_id=r.user_id AND c.thread_id=r.thread_id "
                "AND s.user_id=r.user_id AND s.thread_id=r.thread_id "
                "AND c.state='cloning' "
                "AND c.started_at>extract(epoch FROM clock_timestamp())-90) "
                f"{_OWNED_JOIN}AND r.repository_id=:repository_id"
            ),
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "repository_id": repository_id,
                "intent_id": intent_id,
            },
        )
        return result.scalar_one_or_none() is True

    @connection()
    async def is_clone_destination(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        repository_id: UUID,
        session: AsyncSession | None = None,
    ) -> bool | None:
        result = await require_session(session).execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM profile.ide_clone_intent c "
                "WHERE c.repository_id=r.repository_id) "
                f"{_OWNED_JOIN}AND r.repository_id=:repository_id"
            ),
            {"thread_id": thread_id, "user_id": user_id, "repository_id": repository_id},
        )
        return result.scalar_one_or_none()

    @connection()
    async def is_onboarding_owned(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        repository_id: UUID,
        session: AsyncSession | None = None,
    ) -> bool | None:
        session = require_session(session)
        result = await session.execute(
            text(f"SELECT r.onboarding_created {_OWNED_JOIN}AND r.repository_id = :repository_id"),
            {"thread_id": thread_id, "user_id": user_id, "repository_id": repository_id},
        )
        return result.scalar_one_or_none()

    @connection()
    async def ensure_default(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        session: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        """Serialize first-entry identity across tabs, reloads and explicit setup.

        Only descriptor persistence lives in this short transaction. Runtime
        allocation, Git and network calls must never run while holding this lock.
        """
        session = require_session(session)
        params = {"thread_id": thread_id, "user_id": user_id}
        await session.execute(
            text(
                "INSERT INTO profile.chat_threads "
                "(thread_id, user_id, title, created_at, updated_at) "
                "VALUES (:thread_id, :user_id, :title, NOW(), NOW()) "
                "ON CONFLICT (thread_id) DO NOTHING"
            ),
            {**params, "title": "Новый проект"},
        )
        owner = await session.execute(
            text(
                "SELECT thread_id FROM profile.chat_threads "
                "WHERE thread_id = :thread_id AND user_id = :user_id FOR UPDATE"
            ),
            params,
        )
        if owner.first() is None:
            return None
        existing = await session.execute(
            text(
                f"SELECT {_COLUMNS} {_OWNED_JOIN}"
                "ORDER BY r.created_at DESC, r.repository_id DESC LIMIT 1"
            ),
            params,
        )
        row = existing.mappings().first()
        if row is None:
            inserted = await session.execute(
                text(
                    "INSERT INTO profile.ide_repository "
                    "(repository_id, thread_id, user_id, creation_intent_id, name, "
                    "onboarding_created) VALUES (:repository_id, :thread_id, :user_id, "
                    ":creation_intent_id, :name, TRUE) RETURNING repository_id, name, created_at"
                ),
                {
                    **params,
                    "repository_id": uuid4(),
                    "creation_intent_id": uuid4(),
                    "name": "Новый проект",
                },
            )
            row = inserted.mappings().first()
        return dict(row) if row is not None else None

    @connection()
    async def list_owned(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        limit: int,
        offset: int,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]] | None:
        session = require_session(session)
        params = {"thread_id": thread_id, "user_id": user_id}
        owner = await session.execute(
            text("SELECT user_id FROM profile.chat_threads WHERE thread_id = :thread_id"),
            params,
        )
        row = owner.first()
        # A new Chat URL already has a UUID, but is persisted only by an
        # explicit action. Reading that draft is empty, never a write.
        if row is None:
            return []
        if str(row[0]) != str(user_id):
            return None
        rows = await session.execute(
            text(
                f"SELECT {_COLUMNS} {_OWNED_JOIN}"
                "ORDER BY r.created_at DESC, r.repository_id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        )
        return [dict(row) for row in rows.mappings().all()]

    @connection()
    async def get_owned(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        repository_id: UUID,
        session: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        session = require_session(session)
        result = await session.execute(
            text(f"SELECT {_COLUMNS} {_OWNED_JOIN}AND r.repository_id = :repository_id"),
            {"thread_id": thread_id, "user_id": user_id, "repository_id": repository_id},
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    @connection()
    async def register(
        self,
        *,
        thread_id: UUID,
        user_id: UUID,
        creation_intent_id: UUID,
        name: str,
        create_thread_if_missing: bool = False,
        session: AsyncSession | None = None,
    ) -> dict[str, Any] | None:
        session = require_session(session)
        params = {
            "thread_id": thread_id,
            "user_id": user_id,
            "creation_intent_id": creation_intent_id,
        }
        if create_thread_if_missing:
            # Same transaction as descriptor creation; ON CONFLICT cannot take
            # ownership, rename an existing thread or undo a concurrent winner.
            await session.execute(
                text(
                    "INSERT INTO profile.chat_threads "
                    "(thread_id, user_id, title, created_at, updated_at) "
                    "VALUES (:thread_id, :user_id, :title, NOW(), NOW()) "
                    "ON CONFLICT (thread_id) DO NOTHING"
                ),
                {"thread_id": thread_id, "user_id": user_id, "title": name},
            )
        # Keep a concurrent thread deletion behind this short transaction. Never
        # allocate or infer ownership from a missing thread, including draft IDs.
        owner = await session.execute(
            text(
                "SELECT thread_id FROM profile.chat_threads "
                "WHERE thread_id = :thread_id AND user_id = :user_id FOR KEY SHARE"
            ),
            params,
        )
        if owner.first() is None:
            return None
        result = await session.execute(
            text(
                "INSERT INTO profile.ide_repository "
                "(repository_id, thread_id, user_id, creation_intent_id, name) "
                "VALUES (:repository_id, :thread_id, :user_id, :creation_intent_id, :name) "
                "ON CONFLICT (user_id, thread_id, creation_intent_id) DO NOTHING "
                "RETURNING repository_id, name, created_at"
            ),
            {**params, "repository_id": uuid4(), "name": name},
        )
        row = result.mappings().first()
        if row is None:
            # READ COMMITTED observes the committed winner after ON CONFLICT
            # waits. A lost acknowledgement reuses the same opaque descriptor.
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} {_OWNED_JOIN}AND r.creation_intent_id = :creation_intent_id"
                ),
                params,
            )
            row = result.mappings().first()
        return dict(row) if row is not None else None
