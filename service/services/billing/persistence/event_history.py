from __future__ import annotations

import json
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.billing.persistence.sql import (
    _INSERT_FLAG_EVENT_SQL,
    _INSERT_USAGE_EVENT_SQL,
    _RECENT_EVENTS_SQL,
    _USAGE_TOTALS_SQL,
)
from service.shared.repositories.decorators.session_processor import connection, require_session


def _public_event(row) -> dict[str, Any]:
    """Map an audit row to the deliberately small billing-history contract."""
    raw_meta = row[4]
    if isinstance(raw_meta, dict):
        meta = raw_meta
    elif raw_meta:
        try:
            meta = json.loads(raw_meta)
        except (ValueError, TypeError):
            meta = {}
    else:
        meta = {}
    return {
        "event_type": row[0],
        "tokens": int(row[1]) if row[1] is not None else None,
        "amount": float(row[2]) if row[2] is not None else None,
        "currency": row[3],
        "credits": int(meta.get("credits", 0) or 0),
        # Never expose internal cost fields from metadata in the user history.
        "model": meta.get("model"),
        "created_at": row[5].isoformat() if hasattr(row[5], "isoformat") else str(row[5]),
    }


class BillingEventHistoryMixin:
    """User-visible billing-history queries and append-only audit flags."""

    @connection()
    async def record_flag(
        self,
        *,
        user_id: str,
        event_type: str,
        metadata: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        session = require_session(session)
        await session.execute(
            text(_INSERT_FLAG_EVENT_SQL),
            {
                "user_id": str(user_id),
                "event_type": event_type,
                "metadata": json.dumps(metadata or {}, ensure_ascii=False),
            },
        )

    @connection()
    async def fetch_recent_events(
        self, *, user_id: str, limit: int = 50, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        session = require_session(session)
        rows = (
            await session.execute(
                text(_RECENT_EVENTS_SQL), {"uid": str(user_id), "lim": int(limit)}
            )
        ).fetchall()
        return [_public_event(row) for row in rows]

    @connection()
    async def fetch_events_page(
        self,
        *,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        types: list[str] | None = None,
        session: AsyncSession | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        session = require_session(session)
        where = "WHERE user_id = CAST(:uid AS uuid)"
        params: dict[str, Any] = {"uid": str(user_id)}
        if types:
            where += " AND event_type IN :types"
            params["types"] = list(types)

        rows_stmt = text(
            "SELECT event_type, tokens, amount, currency, metadata, created_at "
            f"FROM profile.billing_events {where} "
            "ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        )
        count_stmt = text(f"SELECT COUNT(*) FROM profile.billing_events {where}")
        if types:
            rows_stmt = rows_stmt.bindparams(bindparam("types", expanding=True))
            count_stmt = count_stmt.bindparams(bindparam("types", expanding=True))

        rows = (
            await session.execute(rows_stmt, {**params, "lim": int(limit), "off": int(offset)})
        ).fetchall()
        total = (await session.execute(count_stmt, params)).scalar() or 0
        return [_public_event(row) for row in rows], int(total)

    @connection()
    async def record_usage_event(
        self,
        *,
        user_id: str,
        tokens: int,
        metadata: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        """Append a non-idempotent usage audit event for an existing user."""
        session = require_session(session)
        await session.execute(
            text(_INSERT_USAGE_EVENT_SQL),
            {
                "user_id": str(user_id),
                "event_type": "usage",
                "tokens": int(tokens),
                "metadata": json.dumps(metadata or {}, ensure_ascii=False),
            },
        )

    @connection()
    async def fetch_usage_totals(
        self, *, since, session: AsyncSession | None = None
    ) -> dict[str, float]:
        session = require_session(session)
        row = (await session.execute(text(_USAGE_TOTALS_SQL), {"since": since})).first()
        if row is None:
            return {"credits": 0, "raw_cost_rub": 0.0, "requests": 0}
        return {
            "credits": int(row[0] or 0),
            "raw_cost_rub": float(row[1] or 0),
            "requests": int(row[2] or 0),
        }
