"""Репозиторий runtime-настроек (profile.app_settings: key → JSONB)."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

logger = logging.getLogger(__name__)

_UPSERT_SQL = (
    "INSERT INTO profile.app_settings (key, value, updated_by) "
    "VALUES (:key, CAST(:value AS jsonb), :updated_by) "
    "ON CONFLICT (key) DO UPDATE SET "
    "value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = now()"
)


class AppSettingsRepository(BaseRepository):
    @connection()
    async def get_all(self, *, session: AsyncSession | None = None) -> dict[str, Any]:
        """Снимок всей таблицы настроек: {key: value(decoded)}."""
        session = require_session(session)
        rows = (await session.execute(text("SELECT key, value FROM profile.app_settings"))).all()
        out: dict[str, Any] = {}
        for key, value in rows:
            # JSONB обычно приходит уже декодированным; строку — добиваем json.loads.
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except Exception:
                    pass
            out[str(key)] = value
        return out

    @connection()
    async def upsert(
        self,
        *,
        key: str,
        value: Any,
        updated_by: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        session = require_session(session)
        await session.execute(
            text(_UPSERT_SQL),
            {"key": key, "value": json.dumps(value, ensure_ascii=False), "updated_by": updated_by},
        )

    @connection()
    async def delete(self, *, key: str, session: AsyncSession | None = None) -> None:
        session = require_session(session)
        await session.execute(
            text("DELETE FROM profile.app_settings WHERE key = :key"), {"key": key}
        )
