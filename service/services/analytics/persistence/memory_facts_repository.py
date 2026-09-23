from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

logger = logging.getLogger(__name__)


class MemoryFactsRepository(BaseRepository):
    """Собственный реестр долговременных фактов (profile.user_memory_facts).

    Полностью под нашим контролем: структурированные русскоязычные факты, дедуп
    по (user_id, content_hash), осмысленная (или пустая) уверенность. Заменяет
    free-form экстракцию MemOS как источник истины для дравера памяти и контекста.
    """

    @connection()
    async def list_facts(
        self,
        *,
        user_id: str,
        limit: int = 50,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        session = require_session(session)
        result = await session.execute(
            text(
                "SELECT id, fact_type, fact_key, fact_value, confidence, "
                "       source_thread_id, updated_at "
                "FROM profile.user_memory_facts "
                "WHERE user_id = :user_id "
                "ORDER BY updated_at DESC "
                "LIMIT :limit"
            ),
            {"user_id": user_id, "limit": int(limit)},
        )
        rows = result.fetchall()
        facts: list[dict[str, Any]] = []
        for row in rows:
            facts.append(
                {
                    "id": str(row[0]),
                    "fact_type": str(row[1] or "general"),
                    "fact_key": str(row[2] or ""),
                    "fact_value": str(row[3] or ""),
                    "confidence": float(row[4]) if row[4] is not None else None,
                    "source_thread_id": str(row[5]) if row[5] is not None else None,
                    "updated_at": row[6].isoformat() if row[6] is not None else None,
                }
            )
        return facts

    @connection()
    async def upsert_fact(
        self,
        *,
        fact_id: str,
        user_id: str,
        fact_type: str,
        fact_key: str,
        fact_value: str,
        content_hash: str,
        confidence: float | None = None,
        source_thread_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        """Создать/обновить факт. Дедуп на запись по (user_id, content_hash):
        повтор того же нормализованного факта лишь освежает значение и updated_at.
        """
        session = require_session(session)
        await session.execute(
            text(
                "INSERT INTO profile.user_memory_facts "
                "(id, user_id, fact_type, fact_key, fact_value, content_hash, "
                " confidence, source_thread_id) "
                "VALUES (:id, :user_id, :fact_type, :fact_key, :fact_value, "
                " :content_hash, :confidence, :source_thread_id) "
                "ON CONFLICT (user_id, content_hash) DO UPDATE SET "
                " fact_type = EXCLUDED.fact_type, "
                " fact_key = EXCLUDED.fact_key, "
                " fact_value = EXCLUDED.fact_value, "
                " confidence = EXCLUDED.confidence, "
                " source_thread_id = EXCLUDED.source_thread_id, "
                " updated_at = now()"
            ),
            {
                "id": fact_id,
                "user_id": user_id,
                "fact_type": fact_type,
                "fact_key": fact_key,
                "fact_value": fact_value,
                "content_hash": content_hash,
                "confidence": confidence,
                "source_thread_id": source_thread_id,
            },
        )

    @connection()
    async def delete_fact(
        self,
        *,
        user_id: str,
        fact_id: str,
        session: AsyncSession | None = None,
    ) -> bool:
        session = require_session(session)
        result = await session.execute(
            text(
                "DELETE FROM profile.user_memory_facts WHERE user_id = :user_id AND id = :fact_id"
            ),
            {"user_id": user_id, "fact_id": fact_id},
        )
        return bool(result.rowcount)

    @connection()
    async def delete_all_facts(
        self,
        *,
        user_id: str,
        session: AsyncSession | None = None,
    ) -> int:
        """Стереть ВСЕ факты пользователя. Возвращает сколько строк удалено.

        ⚠️ `user_id` обязателен и подставляется параметром: запрос без него удалил бы
        таблицу целиком, то есть чужую память. Счётчик возвращаем настоящий (`rowcount`),
        а не факт успеха: «стёрли 34» и «стирать было нечего» — разные новости для того,
        кто нажал кнопку.
        """
        if not str(user_id or "").strip():
            return 0
        session = require_session(session)
        result = await session.execute(
            text("DELETE FROM profile.user_memory_facts WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return int(result.rowcount or 0)

    @connection()
    async def count_facts(
        self,
        *,
        user_id: str,
        session: AsyncSession | None = None,
    ) -> int:
        session = require_session(session)
        result = await session.execute(
            text("SELECT count(*) FROM profile.user_memory_facts WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        value = result.scalar_one_or_none()
        return int(value or 0)
