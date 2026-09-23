from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.billing.persistence.sql import (
    _CLEANUP_EXPIRED_RESERVATIONS_SQL,
    _RESERVATION_SNAPSHOT_SQL,
)
from service.shared.repositories.decorators.session_processor import connection, require_session


class ReservationMaintenanceMixin:
    @connection()
    async def cleanup_expired_reservations(self, *, session: AsyncSession | None = None) -> int:
        """Release only expired active reservations; committed records are immutable."""
        session = require_session(session)
        rows = (await session.execute(text(_CLEANUP_EXPIRED_RESERVATIONS_SQL))).fetchall()
        return len(rows)

    @connection()
    async def fetch_reservation_snapshot(
        self, *, session: AsyncSession | None = None
    ) -> dict[str, int]:
        session = require_session(session)
        row = (await session.execute(text(_RESERVATION_SNAPSHOT_SQL))).first()
        return {"active": int(row[0] or 0) if row else 0, "expired": int(row[1] or 0) if row else 0}
