"""Репозиторий админ-операций: роль is_admin и (Фаза C) управление пользователями."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

logger = logging.getLogger(__name__)


class AdminRepository(BaseRepository):
    @connection()
    async def fetch_is_admin(self, *, user_id: str, session: AsyncSession | None = None) -> bool:
        session = require_session(session)
        row = (
            await session.execute(
                text("SELECT is_admin FROM profile.user WHERE id = CAST(:uid AS uuid)"),
                {"uid": str(user_id)},
            )
        ).first()
        return bool(row[0]) if row is not None else False

    @connection()
    async def set_is_admin(
        self, *, user_id: str, is_admin: bool, session: AsyncSession | None = None
    ) -> bool:
        session = require_session(session)
        result = await session.execute(
            text("UPDATE profile.user SET is_admin = :flag WHERE id = CAST(:uid AS uuid)"),
            {"flag": bool(is_admin), "uid": str(user_id)},
        )
        return (result.rowcount or 0) > 0

    @connection()
    async def list_users(
        self,
        *,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """Список пользователей с балансом докуп-кошелька (для админки)."""
        session = require_session(session)
        where = ""
        params: dict[str, Any] = {"limit": int(limit), "offset": int(offset)}
        if query:
            where = "WHERE u.email ILIKE :q OR CAST(u.id AS text) ILIKE :q"
            params["q"] = f"%{query}%"
        rows = (
            await session.execute(
                text(
                    "SELECT CAST(u.id AS text), u.email, u.first_name, u.plan, "
                    "u.topup_credit_balance, u.is_admin, u.is_active "
                    f"FROM profile.user u {where} "
                    "ORDER BY u.email LIMIT :limit OFFSET :offset"
                ),
                params,
            )
        ).all()
        return [
            {
                "id": r[0],
                "email": r[1],
                "first_name": r[2],
                "plan": r[3],
                "topup_credit_balance": int(r[4] or 0),
                "is_admin": bool(r[5]),
                "is_active": bool(r[6]),
            }
            for r in rows
        ]

    @connection()
    async def get_user(
        self, *, user_id: str, session: AsyncSession | None = None
    ) -> dict[str, Any] | None:
        session = require_session(session)
        row = (
            await session.execute(
                text(
                    "SELECT CAST(u.id AS text), u.email, u.first_name, u.plan, "
                    "u.topup_credit_balance, u.is_admin, u.is_active, u.created_at "
                    "FROM profile.user u WHERE u.id = CAST(:uid AS uuid)"
                ),
                {"uid": str(user_id)},
            )
        ).first()
        if row is None:
            return None
        events = (
            await session.execute(
                text(
                    "SELECT event_type, tokens, amount, currency, created_at "
                    "FROM profile.billing_events WHERE user_id = CAST(:uid AS uuid) "
                    "ORDER BY created_at DESC LIMIT 20"
                ),
                {"uid": str(user_id)},
            )
        ).all()
        return {
            "id": row[0],
            "email": row[1],
            "first_name": row[2],
            "plan": row[3],
            "topup_credit_balance": int(row[4] or 0),
            "is_admin": bool(row[5]),
            "is_active": bool(row[6]),
            "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
            "recent_events": [
                {
                    "event_type": e[0],
                    "tokens": int(e[1] or 0),
                    "amount": float(e[2]) if e[2] is not None else None,
                    "currency": e[3],
                    "created_at": e[4].isoformat() if hasattr(e[4], "isoformat") else str(e[4]),
                }
                for e in events
            ],
        }

    @connection()
    async def list_user_events(
        self, *, user_id: str, limit: int, offset: int, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        """Страница истории операций пользователя (billing_events, свежие первыми)."""
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "SELECT event_type, tokens, amount, currency, created_at "
                    "FROM profile.billing_events WHERE user_id = CAST(:uid AS uuid) "
                    "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                ),
                {"uid": str(user_id), "limit": limit, "offset": offset},
            )
        ).all()
        return [
            {
                "event_type": e[0],
                "tokens": int(e[1] or 0),
                "amount": float(e[2]) if e[2] is not None else None,
                "currency": e[3],
                "created_at": e[4].isoformat() if hasattr(e[4], "isoformat") else str(e[4]),
            }
            for e in rows
        ]

    @connection()
    async def adjust_topup_credits(
        self,
        *,
        user_id: str,
        delta: int,
        reason: str,
        updated_by: str,
        session: AsyncSession | None = None,
    ) -> int:
        """Скорректировать докуп-кошелёк (±), не ниже нуля, + аудит billing_event."""
        session = require_session(session)
        row = (
            await session.execute(
                text(
                    "UPDATE profile.user SET topup_credit_balance = "
                    "GREATEST(0, topup_credit_balance + :delta) "
                    "WHERE id = CAST(:uid AS uuid) RETURNING topup_credit_balance"
                ),
                {"delta": int(delta), "uid": str(user_id)},
            )
        ).first()
        if row is None:
            raise ValueError("user not found")
        await session.execute(
            text(
                "INSERT INTO profile.billing_events (user_id, event_type, tokens, metadata) "
                "VALUES (CAST(:uid AS uuid), 'admin_adjust', :delta, CAST(:meta AS jsonb))"
            ),
            {
                "uid": str(user_id),
                "delta": int(delta),
                "meta": json.dumps(
                    {"reason": reason, "by": updated_by, "delta": int(delta)}, ensure_ascii=False
                ),
            },
        )
        return int(row[0] or 0)

    @connection()
    async def set_active(
        self, *, user_id: str, is_active: bool, session: AsyncSession | None = None
    ) -> bool:
        session = require_session(session)
        result = await session.execute(
            text("UPDATE profile.user SET is_active = :flag WHERE id = CAST(:uid AS uuid)"),
            {"flag": bool(is_active), "uid": str(user_id)},
        )
        # При блокировке гасим сессии пользователя (session-store TTL + login-гейт
        # довершают; stateless JWT доживает до истечения).
        if not is_active:
            await session.execute(
                text("DELETE FROM session.user_session WHERE user_id = CAST(:uid AS uuid)"),
                {"uid": str(user_id)},
            )
        return (result.rowcount or 0) > 0

    @connection()
    async def set_plan(
        self, *, user_id: str, plan: str, session: AsyncSession | None = None
    ) -> bool:
        session = require_session(session)
        result = await session.execute(
            text("UPDATE profile.user SET plan = :plan WHERE id = CAST(:uid AS uuid)"),
            {"plan": str(plan), "uid": str(user_id)},
        )
        return (result.rowcount or 0) > 0

    @connection()
    async def set_topup_credits(
        self,
        *,
        user_id: str,
        value: int,
        reason: str,
        updated_by: str,
        session: AsyncSession | None = None,
    ) -> int:
        """Задать докуп-баланс абсолютным значением (>=0) + аудит billing_event."""
        session = require_session(session)
        row = (
            await session.execute(
                text(
                    "UPDATE profile.user SET topup_credit_balance = GREATEST(0, :value) "
                    "WHERE id = CAST(:uid AS uuid) RETURNING topup_credit_balance"
                ),
                {"value": int(value), "uid": str(user_id)},
            )
        ).first()
        if row is None:
            raise ValueError("user not found")
        await session.execute(
            text(
                "INSERT INTO profile.billing_events (user_id, event_type, tokens, metadata) "
                "VALUES (CAST(:uid AS uuid), 'admin_adjust', :value, CAST(:meta AS jsonb))"
            ),
            {
                "uid": str(user_id),
                "value": int(value),
                "meta": json.dumps(
                    {"reason": reason, "by": updated_by, "set_absolute": int(value)},
                    ensure_ascii=False,
                ),
            },
        )
        return int(row[0] or 0)

    @connection()
    async def fetch_usage_daily_all(
        self, *, since, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "SELECT day, SUM(requests), SUM(credits), SUM(tokens) "
                    "FROM profile.usage_daily WHERE day >= :since GROUP BY day ORDER BY day"
                ),
                {"since": since},
            )
        ).all()
        return [
            {
                "day": r[0],
                "requests": int(r[1] or 0),
                "credits": int(r[2] or 0),
                "tokens": int(r[3] or 0),
            }
            for r in rows
        ]

    @connection()
    async def fetch_usage_events_all(
        self, *, since, limit: int = 5000, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "SELECT tokens, metadata FROM profile.billing_events "
                    "WHERE event_type = 'usage' AND created_at >= :since "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                {"since": since, "lim": int(limit)},
            )
        ).all()
        out: list[dict[str, Any]] = []
        for r in rows:
            meta = r[1]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (ValueError, TypeError):
                    meta = {}
            out.append({"tokens": int(r[0] or 0), "metadata": meta or {}})
        return out

    @connection()
    async def fetch_recent_flags(
        self, *, limit: int = 50, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "SELECT CAST(user_id AS text), metadata, created_at "
                    "FROM profile.billing_events WHERE event_type = 'abuse_flag' "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                {"lim": int(limit)},
            )
        ).all()
        out: list[dict[str, Any]] = []
        for r in rows:
            meta = r[1]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (ValueError, TypeError):
                    meta = {}
            out.append(
                {
                    "user_id": r[0],
                    "metadata": meta or {},
                    "created_at": r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
                }
            )
        return out

    # ─── Финансы и активность (админ-аналитика) ──────────────────────────────
    # Доход берём из profile.billing_events.amount (в ₽ пишутся ТОЛЬКО платёжные
    # события: 'subscription_grant', 'topup', 'refund'), расход — из
    # profile.usage_daily.raw_cost_rub (реальная себестоимость провайдеру).
    # Отсюда честная чистая прибыль = доход − возвраты − себестоимость.

    @connection()
    async def fetch_revenue_daily(
        self, *, since, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        """Выручка по дням: подписки / пополнения / возвраты (₽ и количество)."""
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "SELECT created_at::date AS day, "
                    "COALESCE(SUM(amount) FILTER (WHERE event_type = 'subscription_grant'), 0), "
                    "COALESCE(SUM(amount) FILTER (WHERE event_type = 'topup'), 0), "
                    "COALESCE(SUM(amount) FILTER (WHERE event_type = 'refund'), 0), "
                    "COUNT(*) FILTER (WHERE event_type = 'subscription_grant'), "
                    "COUNT(*) FILTER (WHERE event_type = 'topup'), "
                    "COUNT(*) FILTER (WHERE event_type = 'refund') "
                    "FROM profile.billing_events "
                    "WHERE created_at >= :since "
                    "AND event_type IN ('subscription_grant', 'topup', 'refund') "
                    "GROUP BY 1 ORDER BY 1"
                ),
                {"since": since},
            )
        ).all()
        return [
            {
                "day": r[0],
                "subscription_rub": float(r[1] or 0),
                "topup_rub": float(r[2] or 0),
                "refund_rub": float(r[3] or 0),
                "subscription_count": int(r[4] or 0),
                "topup_count": int(r[5] or 0),
                "refund_count": int(r[6] or 0),
            }
            for r in rows
        ]

    @connection()
    async def fetch_cost_daily(
        self, *, since, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        """Себестоимость и потребление по дням + активные пользователи (DAU)."""
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "SELECT day, COALESCE(SUM(raw_cost_rub), 0), COALESCE(SUM(requests), 0), "
                    "COALESCE(SUM(tokens), 0), COALESCE(SUM(credits), 0), "
                    "COUNT(DISTINCT user_id) "
                    "FROM profile.usage_daily WHERE day >= :since GROUP BY day ORDER BY day"
                ),
                {"since": since},
            )
        ).all()
        return [
            {
                "day": r[0],
                "cost_rub": float(r[1] or 0),
                "requests": int(r[2] or 0),
                "tokens": int(r[3] or 0),
                "credits": int(r[4] or 0),
                "active_users": int(r[5] or 0),
            }
            for r in rows
        ]

    @connection()
    async def fetch_new_users_daily(
        self, *, since, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        """Регистрации по дням."""
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "SELECT created_at::date AS day, COUNT(*) "
                    "FROM profile.user WHERE created_at >= :since GROUP BY 1 ORDER BY 1"
                ),
                {"since": since},
            )
        ).all()
        return [{"day": r[0], "count": int(r[1] or 0)} for r in rows]

    @connection()
    async def fetch_activity_hourly(
        self, *, since, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        """Активность по часам суток (UTC): запросы и уникальные пользователи."""
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "SELECT EXTRACT(HOUR FROM created_at)::int AS hour, COUNT(*), "
                    "COUNT(DISTINCT user_id) "
                    "FROM profile.billing_events "
                    "WHERE event_type = 'usage' AND created_at >= :since "
                    "GROUP BY 1 ORDER BY 1"
                ),
                {"since": since},
            )
        ).all()
        by_hour = {int(r[0]): (int(r[1] or 0), int(r[2] or 0)) for r in rows}
        return [
            {"hour": h, "requests": by_hour.get(h, (0, 0))[0], "users": by_hour.get(h, (0, 0))[1]}
            for h in range(24)
        ]

    @connection()
    async def fetch_activity_weekday(
        self, *, since, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        """Активность по дням недели (ISO: 1 = понедельник … 7 = воскресенье)."""
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "SELECT EXTRACT(ISODOW FROM created_at)::int AS dow, COUNT(*), "
                    "COUNT(DISTINCT user_id) "
                    "FROM profile.billing_events "
                    "WHERE event_type = 'usage' AND created_at >= :since "
                    "GROUP BY 1 ORDER BY 1"
                ),
                {"since": since},
            )
        ).all()
        by_dow = {int(r[0]): (int(r[1] or 0), int(r[2] or 0)) for r in rows}
        return [
            {"dow": d, "requests": by_dow.get(d, (0, 0))[0], "users": by_dow.get(d, (0, 0))[1]}
            for d in range(1, 8)
        ]

    @connection()
    async def fetch_user_totals(self, *, session: AsyncSession | None = None) -> dict[str, Any]:
        """Срез по базе пользователей (всего / активные / платящие / админы)."""
        session = require_session(session)
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*), COUNT(*) FILTER (WHERE is_active), "
                    "COUNT(*) FILTER (WHERE plan <> 'free'), "
                    "COUNT(*) FILTER (WHERE is_admin), "
                    "COUNT(*) FILTER (WHERE email_verified) "
                    "FROM profile.user"
                )
            )
        ).first()
        if row is None:
            return {"total": 0, "active": 0, "paying": 0, "admins": 0, "verified": 0}
        return {
            "total": int(row[0] or 0),
            "active": int(row[1] or 0),
            "paying": int(row[2] or 0),
            "admins": int(row[3] or 0),
            "verified": int(row[4] or 0),
        }

    @connection()
    async def fetch_plan_distribution(
        self, *, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        """Распределение пользователей по тарифам (для MRR и структуры базы)."""
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "SELECT plan, COUNT(*) FROM profile.user "
                    "WHERE is_active GROUP BY plan ORDER BY 2 DESC"
                )
            )
        ).all()
        return [{"plan": r[0] or "free", "users": int(r[1] or 0)} for r in rows]

    @connection()
    async def fetch_sales_breakdown(
        self, *, since, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        """Продажи в разрезе позиции: план подписки / пакет пополнения."""
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "SELECT event_type, "
                    "COALESCE(metadata->>'plan', metadata->>'pack_id', 'unknown') AS item, "
                    "COUNT(*), COALESCE(SUM(amount), 0) "
                    "FROM profile.billing_events "
                    "WHERE created_at >= :since "
                    "AND event_type IN ('subscription_grant', 'topup') "
                    "GROUP BY 1, 2 ORDER BY 4 DESC"
                ),
                {"since": since},
            )
        ).all()
        return [
            {
                "kind": "subscription" if r[0] == "subscription_grant" else "topup",
                "item": r[1],
                "count": int(r[2] or 0),
                "amount_rub": float(r[3] or 0),
            }
            for r in rows
        ]

    @connection()
    async def fetch_finance_windows(
        self, *, session: AsyncSession | None = None
    ) -> dict[str, dict[str, float]]:
        """Доход/возвраты за СЕГОДНЯ, текущую ISO-неделю и текущий календарный месяц."""
        session = require_session(session)
        paid = "event_type IN ('subscription_grant', 'topup')"
        row = (
            await session.execute(
                text(
                    "SELECT "
                    f"COALESCE(SUM(amount) FILTER (WHERE {paid} "
                    "AND created_at >= date_trunc('day', now())), 0), "
                    "COALESCE(SUM(amount) FILTER (WHERE event_type = 'refund' "
                    "AND created_at >= date_trunc('day', now())), 0), "
                    f"COALESCE(SUM(amount) FILTER (WHERE {paid} "
                    "AND created_at >= date_trunc('week', now())), 0), "
                    "COALESCE(SUM(amount) FILTER (WHERE event_type = 'refund' "
                    "AND created_at >= date_trunc('week', now())), 0), "
                    f"COALESCE(SUM(amount) FILTER (WHERE {paid}), 0), "
                    "COALESCE(SUM(amount) FILTER (WHERE event_type = 'refund'), 0) "
                    "FROM profile.billing_events "
                    "WHERE created_at >= date_trunc('month', now())"
                )
            )
        ).first()
        vals = [float(v or 0) for v in (row or (0, 0, 0, 0, 0, 0))]
        return {
            "today": {"revenue_rub": vals[0], "refund_rub": vals[1]},
            "week": {"revenue_rub": vals[2], "refund_rub": vals[3]},
            "month": {"revenue_rub": vals[4], "refund_rub": vals[5]},
        }

    @connection()
    async def fetch_cost_windows(self, *, session: AsyncSession | None = None) -> dict[str, float]:
        """Себестоимость за сегодня / текущую неделю / текущий месяц."""
        session = require_session(session)
        row = (
            await session.execute(
                text(
                    "SELECT "
                    "COALESCE(SUM(raw_cost_rub) FILTER (WHERE day = CURRENT_DATE), 0), "
                    "COALESCE(SUM(raw_cost_rub) FILTER "
                    "(WHERE day >= date_trunc('week', CURRENT_DATE)::date), 0), "
                    "COALESCE(SUM(raw_cost_rub), 0) "
                    "FROM profile.usage_daily "
                    "WHERE day >= date_trunc('month', CURRENT_DATE)::date"
                )
            )
        ).first()
        vals = [float(v or 0) for v in (row or (0, 0, 0))]
        return {"today": vals[0], "week": vals[1], "month": vals[2]}

    @connection()
    async def fetch_period_counts(
        self, *, since, session: AsyncSession | None = None
    ) -> dict[str, int]:
        """Уникальные плательщики и активные пользователи за период (для ARPU/ARPPU)."""
        session = require_session(session)
        paying = (
            await session.execute(
                text(
                    "SELECT COUNT(DISTINCT user_id) FROM profile.billing_events "
                    "WHERE created_at >= :since "
                    "AND event_type IN ('subscription_grant', 'topup')"
                ),
                {"since": since},
            )
        ).scalar()
        active = (
            await session.execute(
                text("SELECT COUNT(DISTINCT user_id) FROM profile.usage_daily WHERE day >= :since"),
                {"since": since},
            )
        ).scalar()
        return {"paying_customers": int(paying or 0), "active_users": int(active or 0)}

    @connection()
    async def fetch_top_users(
        self, *, since, limit: int = 10, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        """Топ пользователей за период: выручка, себестоимость, потребление."""
        session = require_session(session)
        rows = (
            await session.execute(
                text(
                    "WITH rev AS ("
                    "  SELECT user_id, SUM(amount) AS revenue FROM profile.billing_events "
                    "  WHERE created_at >= :since "
                    "  AND event_type IN ('subscription_grant', 'topup') GROUP BY user_id"
                    "), cst AS ("
                    "  SELECT user_id, SUM(raw_cost_rub) AS cost, SUM(requests) AS requests, "
                    "         SUM(credits) AS credits FROM profile.usage_daily "
                    "  WHERE day >= :since GROUP BY user_id"
                    ") "
                    "SELECT CAST(u.id AS text), u.email, u.plan, "
                    "COALESCE(rev.revenue, 0), COALESCE(cst.cost, 0), "
                    "COALESCE(cst.requests, 0), COALESCE(cst.credits, 0) "
                    "FROM profile.user u "
                    "LEFT JOIN rev ON rev.user_id = u.id "
                    "LEFT JOIN cst ON cst.user_id = u.id "
                    "WHERE COALESCE(rev.revenue, 0) > 0 OR COALESCE(cst.requests, 0) > 0 "
                    "ORDER BY COALESCE(rev.revenue, 0) DESC, COALESCE(cst.cost, 0) DESC "
                    "LIMIT :lim"
                ),
                {"since": since, "lim": int(limit)},
            )
        ).all()
        return [
            {
                "id": r[0],
                "email": r[1],
                "plan": r[2],
                "revenue_rub": float(r[3] or 0),
                "cost_rub": float(r[4] or 0),
                "requests": int(r[5] or 0),
                "credits": int(r[6] or 0),
            }
            for r in rows
        ]
