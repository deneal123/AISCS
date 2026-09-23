from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.billing.persistence.sql import _COST_GUARD_EVENTS_SQL
from service.shared.repositories.decorators.session_processor import connection, require_session


class CostGuardEventsMixin:
    @connection()
    async def fetch_cost_guard_events(
        self, *, since: datetime, session: AsyncSession | None = None
    ) -> dict[str, int | float]:
        session = require_session(session)
        row = (await session.execute(text(_COST_GUARD_EVENTS_SQL), {"since": since})).first()
        return {
            "fallback_pricing": int(row[0] or 0) if row else 0,
            "prompt_budget_stops": int(row[1] or 0) if row else 0,
            "raw_cost_rub": float(row[2] or 0) if row else 0.0,
        }
