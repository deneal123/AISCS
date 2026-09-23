"""Репозиторий секретов провайдеров (profile.provider_secrets: provider → шифртекст).

Хранит зашифрованные (Fernet) API-ключи провайдеров для runtime-замены без
рестарта. Значения наружу отдаются только через дешифровку в сервисе; сам
репозиторий оперирует уже зашифрованными строками.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

logger = logging.getLogger(__name__)

_UPSERT_SQL = (
    "INSERT INTO profile.provider_secrets (provider, secret_enc, updated_by) "
    "VALUES (:provider, :secret_enc, :updated_by) "
    "ON CONFLICT (provider) DO UPDATE SET "
    "secret_enc = EXCLUDED.secret_enc, updated_by = EXCLUDED.updated_by, updated_at = now()"
)


class ProviderSecretsRepository(BaseRepository):
    @connection()
    async def get_all(self, *, session: AsyncSession | None = None) -> dict[str, dict[str, Any]]:
        """Снимок таблицы: {provider: {"secret_enc": str, "updated_at": ..., "updated_by": ...}}."""
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "SELECT provider, secret_enc, updated_by, updated_at "
                    "FROM profile.provider_secrets"
                )
            )
        ).all()
        out: dict[str, dict[str, Any]] = {}
        for provider, secret_enc, updated_by, updated_at in rows:
            out[str(provider)] = {
                "secret_enc": secret_enc,
                "updated_by": updated_by,
                "updated_at": updated_at,
            }
        return out

    @connection()
    async def upsert(
        self,
        *,
        provider: str,
        secret_enc: str,
        updated_by: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        session = require_session(session)
        await session.execute(
            text(_UPSERT_SQL),
            {"provider": provider, "secret_enc": secret_enc, "updated_by": updated_by},
        )

    @connection()
    async def delete(self, *, provider: str, session: AsyncSession | None = None) -> None:
        session = require_session(session)
        await session.execute(
            text("DELETE FROM profile.provider_secrets WHERE provider = :provider"),
            {"provider": provider},
        )
