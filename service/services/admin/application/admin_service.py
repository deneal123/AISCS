"""AdminService: админ-роль, runtime-настройки, пользователи, системная аналитика."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from service.services.admin.application.runtime_settings import runtime_settings
from service.services.admin.application.settings_registry import all_specs, coerce_strict, get_spec
from service.settings import config

logger = logging.getLogger(__name__)

_RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}


def _rollup(daily: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Свернуть дневной P&L по неделям ('%G-W%V') или месяцам ('%Y-%m')."""
    fmt = "%G-W%V" if key == "week" else "%Y-%m"
    buckets: dict[str, dict[str, float]] = {}
    for row in daily:
        day = row["day"]
        label = day.strftime(fmt)
        acc = buckets.setdefault(
            label,
            {"revenue_rub": 0.0, "refund_rub": 0.0, "cost_rub": 0.0, "profit_rub": 0.0},
        )
        acc["revenue_rub"] += row["revenue_rub"]
        acc["refund_rub"] += row["refund_rub"]
        acc["cost_rub"] += row["cost_rub"]
        acc["profit_rub"] += row["profit_rub"]
    return [
        {"period": label, **{k: round(v, 2) for k, v in acc.items()}}
        for label, acc in sorted(buckets.items())
    ]


def _build_finance(
    *,
    revenue_daily: list[dict[str, Any]],
    cost_daily: list[dict[str, Any]],
    new_users: list[dict[str, Any]],
    windows_rev: dict[str, dict[str, float]],
    windows_cost: dict[str, float],
    counts: dict[str, int],
    sales: list[dict[str, Any]],
    prev_revenue_daily: list[dict[str, Any]],
    prev_cost_daily: list[dict[str, Any]],
    since,
) -> dict[str, Any]:
    """Слить выручку, себестоимость и регистрации в единый дневной P&L."""
    rev_by_day = {r["day"]: r for r in revenue_daily}
    cost_by_day = {r["day"]: r for r in cost_daily}
    new_by_day = {r["day"]: r["count"] for r in new_users}

    days = sorted(set(rev_by_day) | set(cost_by_day) | set(new_by_day))
    daily: list[dict[str, Any]] = []
    for day in days:
        rev = rev_by_day.get(day, {})
        cst = cost_by_day.get(day, {})
        gross = float(rev.get("subscription_rub", 0)) + float(rev.get("topup_rub", 0))
        refund = float(rev.get("refund_rub", 0))
        cost = float(cst.get("cost_rub", 0))
        daily.append(
            {
                "day": str(day),
                "revenue_rub": round(gross, 2),
                "subscription_rub": round(float(rev.get("subscription_rub", 0)), 2),
                "topup_rub": round(float(rev.get("topup_rub", 0)), 2),
                "refund_rub": round(refund, 2),
                "cost_rub": round(cost, 2),
                "profit_rub": round(gross - refund - cost, 2),
                "subscription_count": int(rev.get("subscription_count", 0)),
                "topup_count": int(rev.get("topup_count", 0)),
                "requests": int(cst.get("requests", 0)),
                "credits": int(cst.get("credits", 0)),
                "active_users": int(cst.get("active_users", 0)),
                "new_users": int(new_by_day.get(day, 0)),
            }
        )
    # Для сверток нужен date, а не строка — считаем на «сырых» днях.
    raw = [
        {
            "day": day,
            "revenue_rub": float(rev_by_day.get(day, {}).get("subscription_rub", 0))
            + float(rev_by_day.get(day, {}).get("topup_rub", 0)),
            "refund_rub": float(rev_by_day.get(day, {}).get("refund_rub", 0)),
            "cost_rub": float(cost_by_day.get(day, {}).get("cost_rub", 0)),
        }
        for day in days
    ]
    for row in raw:
        row["profit_rub"] = row["revenue_rub"] - row["refund_rub"] - row["cost_rub"]

    revenue = sum(r["revenue_rub"] for r in daily)
    refunds = sum(r["refund_rub"] for r in daily)
    cost = sum(r["cost_rub"] for r in daily)
    net = revenue - refunds
    profit = net - cost

    prev_rev = sum(
        float(r.get("subscription_rub", 0)) + float(r.get("topup_rub", 0))
        for r in prev_revenue_daily
        if r["day"] < since
    )
    prev_refunds = sum(
        float(r.get("refund_rub", 0)) for r in prev_revenue_daily if r["day"] < since
    )
    prev_cost = sum(float(r.get("cost_rub", 0)) for r in prev_cost_daily if r["day"] < since)
    prev_profit = prev_rev - prev_refunds - prev_cost

    paying = int(counts.get("paying_customers", 0))
    active = int(counts.get("active_users", 0))

    return {
        "totals": {
            "revenue_rub": round(revenue, 2),
            "subscription_rub": round(sum(r["subscription_rub"] for r in daily), 2),
            "topup_rub": round(sum(r["topup_rub"] for r in daily), 2),
            "refund_rub": round(refunds, 2),
            "net_revenue_rub": round(net, 2),
            "cost_rub": round(cost, 2),
            "profit_rub": round(profit, 2),
            "margin_pct": round(profit / net * 100, 1) if net > 0 else 0.0,
            "subscription_count": sum(r["subscription_count"] for r in daily),
            "topup_count": sum(r["topup_count"] for r in daily),
            "paying_customers": paying,
            "active_users": active,
            "arpu_rub": round(net / active, 2) if active else 0.0,
            "arppu_rub": round(net / paying, 2) if paying else 0.0,
            "conversion_pct": round(paying / active * 100, 1) if active else 0.0,
        },
        "previous": {
            "revenue_rub": round(prev_rev, 2),
            "cost_rub": round(prev_cost, 2),
            "profit_rub": round(prev_profit, 2),
        },
        "windows": {
            "today": {
                "revenue_rub": round(windows_rev["today"]["revenue_rub"], 2),
                "cost_rub": round(windows_cost["today"], 2),
                "profit_rub": round(
                    windows_rev["today"]["revenue_rub"]
                    - windows_rev["today"]["refund_rub"]
                    - windows_cost["today"],
                    2,
                ),
            },
            "week": {
                "revenue_rub": round(windows_rev["week"]["revenue_rub"], 2),
                "cost_rub": round(windows_cost["week"], 2),
                "profit_rub": round(
                    windows_rev["week"]["revenue_rub"]
                    - windows_rev["week"]["refund_rub"]
                    - windows_cost["week"],
                    2,
                ),
            },
            "month": {
                "revenue_rub": round(windows_rev["month"]["revenue_rub"], 2),
                "cost_rub": round(windows_cost["month"], 2),
                "profit_rub": round(
                    windows_rev["month"]["revenue_rub"]
                    - windows_rev["month"]["refund_rub"]
                    - windows_cost["month"],
                    2,
                ),
            },
        },
        "daily": daily,
        "weekly": _rollup(raw, "week"),
        "monthly": _rollup(raw, "month"),
        "sales": sales,
    }


# Кэш статуса провайдеров: последний снимок живой проверки. Обновляется ТОЛЬКО по кнопке
# админа (recheck) или разовым прогревом на старте — без фонового пересчёта на каждый показ
# (убрали постоянный пуллинг). Процесс-локальный, в Redis выносить незачем.
_HEALTH_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}


def _provider_health_status(data: dict[str, Any]) -> dict[str, Any]:
    """Add a stable admin-facing severity without changing provider details."""
    providers = data.get("providers") or {}
    # A provider explicitly disabled by an operator is intentionally outside
    # the route. Its last failed probe must not keep the platform health red.
    configured = [
        info for info in providers.values() if info.get("configured") and not info.get("disabled")
    ]
    unavailable = bool(data.get("unavailable"))
    unreachable = [info for info in configured if not info.get("reachable")]
    active = str(data.get("active_provider") or "")
    active_info = providers.get(active) or {}
    active_unreachable = (
        active
        and active_info.get("configured")
        and not active_info.get("disabled")
        and not active_info.get("reachable")
    )
    if unavailable or active_unreachable:
        level, action = "critical", "Проверьте доступность активного провайдера и ключи доступа."
    elif unreachable:
        level, action = "warning", "Проверьте недоступные провайдеры или оставьте их отключёнными."
    else:
        level, action = "normal", "Действий не требуется."
    observed_at = data.get("observed_at") or datetime.now(UTC).isoformat()
    for name, info in providers.items():
        provider_level = "normal" if info.get("disabled") or info.get("reachable") else "warning"
        if name == active and provider_level != "normal":
            provider_level = "critical"
        info["status"] = provider_level
        from service.services.billing.application.cost_guard_metrics import cost_guard_metrics

        cost_guard_metrics.provider(name, provider_level)
    return {**data, "observed_at": observed_at, "status": {"level": level, "next_action": action}}


class AdminRoleError(Exception):
    """Нарушение правил управления ролью (напр. демоут env-бутстрап админа)."""


class SettingError(Exception):
    """Невалидный ключ/значение настройки (→ 422 на границе)."""


class AdminService:
    def __init__(self, admin_repo: Any, app_settings_repo: Any, profile_cache: Any = None) -> None:
        self._admin_repo = admin_repo
        self._settings_repo = app_settings_repo
        self._profile_cache = profile_cache  # ProfileCachePort — для инвалидации при блоке
        self._cache: dict[str, tuple[bool, float]] = {}  # uid → (flag, expires)
        self._lock = asyncio.Lock()

    async def _invalidate_profile_cache(self, user_id: str, email: str | None) -> None:
        """Сбросить кэш профиля (иначе login увидит устаревший is_active/plan).

        ⚠️ NAMESPACE БЕРЁМ ИЗ ЕДИНОГО ИСТОЧНИКА, А НЕ СТРОКОЙ. Здесь были захардкожены
        `"profile:id"` / `"profile:email"`, а `ProfileService` давно хранит под
        `...:v2` (суффикс появился при миграции формы кэша). Инвалидация промахивалась
        мимо ключа — то есть была NO-OP: админ блокирует пользователя, а его сессия
        живёт до истечения TTL, потому что `is_active` в кэше не сбросился. Комментарий
        выше про «иначе login увидит устаревший is_active» описывал ровно то, чего код
        уже не делал. Импорт констант связывает две стороны намертво.
        """
        if self._profile_cache is None:
            return
        from service.services.profile.application.profile_service import (
            PROFILE_BY_EMAIL_NAMESPACE,
            PROFILE_BY_ID_NAMESPACE,
        )

        try:
            await self._profile_cache.invalidate(PROFILE_BY_ID_NAMESPACE, str(user_id))
            if email:
                await self._profile_cache.invalidate(PROFILE_BY_EMAIL_NAMESPACE, str(email).lower())
        except Exception:  # noqa: BLE001
            logger.debug("profile cache invalidate failed", exc_info=True)

    # --- роль -------------------------------------------------------------- #
    def _ttl(self) -> float:
        try:
            return float(config.admin.admin_role_cache_ttl_sec or 30)
        except Exception:
            return 30.0

    def is_env_admin(self, user_id: str) -> bool:
        return str(user_id).lower() in config.service.admin_user_ids_set

    async def is_admin(self, user_id: str) -> bool:
        if self.is_env_admin(user_id):
            return True
        uid = str(user_id).lower()
        now = time.monotonic()
        cached = self._cache.get(uid)
        if cached and now < cached[1]:
            return cached[0]
        async with self._lock:
            cached = self._cache.get(uid)
            if cached and time.monotonic() < cached[1]:
                return cached[0]
            try:
                flag = await self._admin_repo.fetch_is_admin(user_id=uid)
            except Exception:
                logger.debug("is_admin DB lookup failed; fallback", exc_info=True)
                flag = bool(cached[0]) if cached else False
            self._cache[uid] = (flag, time.monotonic() + self._ttl())
            return flag

    def invalidate(self, user_id: str) -> None:
        self._cache.pop(str(user_id).lower(), None)

    async def set_role(self, *, user_id: str, is_admin: bool) -> bool:
        if not is_admin and self.is_env_admin(user_id):
            raise AdminRoleError("Cannot demote a bootstrap admin (SERVICE__ADMIN_USER_IDS)")
        ok = await self._admin_repo.set_is_admin(user_id=user_id, is_admin=is_admin)
        self.invalidate(user_id)
        return ok

    # --- настройки --------------------------------------------------------- #
    async def get_settings_view(self) -> dict[str, Any]:
        try:
            stored = await self._settings_repo.get_all()
        except Exception:
            logger.debug("settings get_all failed", exc_info=True)
            stored = {}
        items = []
        for spec in all_specs():
            default = getattr(getattr(config, spec.section), spec.field)
            raw = stored.get(spec.key)
            overridden = raw is not None
            if overridden:
                try:
                    value = coerce_strict(spec, raw)
                except ValueError:
                    value = default
            else:
                value = default
            items.append(
                {
                    "key": spec.key,
                    "group": spec.group,
                    "label": spec.label,
                    "description": spec.description,
                    "type": spec.type,
                    "minimum": spec.minimum,
                    "maximum": spec.maximum,
                    "value": value,
                    "default": default,
                    "overridden": overridden,
                }
            )
        return {"settings": items}

    async def set_setting(self, *, key: str, value: Any, updated_by: str) -> dict[str, Any]:
        spec = get_spec(key)
        if spec is None:
            raise SettingError(f"Unknown setting: {key}")
        try:
            coerced = coerce_strict(spec, value)
        except (ValueError, TypeError) as exc:
            raise SettingError(str(exc)) from exc
        await self._settings_repo.upsert(key=key, value=coerced, updated_by=updated_by)
        runtime_settings.invalidate()
        return {"status": "ok", "key": key, "value": coerced}

    async def reset_setting(self, *, key: str) -> dict[str, Any]:
        if get_spec(key) is None:
            raise SettingError(f"Unknown setting: {key}")
        await self._settings_repo.delete(key=key)
        runtime_settings.invalidate()
        return {"status": "ok", "key": key, "reset": True}

    # --- пользователи ------------------------------------------------------ #
    async def list_users(self, *, query: str | None, limit: int, offset: int) -> dict[str, Any]:
        users = await self._admin_repo.list_users(query=query, limit=limit, offset=offset)
        return {"users": users}

    async def get_user(self, *, user_id: str) -> dict[str, Any] | None:
        return await self._admin_repo.get_user(user_id=user_id)

    async def list_user_events(self, *, user_id: str, limit: int, offset: int) -> dict[str, Any]:
        events = await self._admin_repo.list_user_events(
            user_id=user_id, limit=limit, offset=offset
        )
        return {"events": events}

    async def adjust_credits(
        self, *, user_id: str, delta: int, reason: str, updated_by: str
    ) -> dict[str, Any]:
        balance = await self._admin_repo.adjust_topup_credits(
            user_id=user_id, delta=int(delta), reason=reason or "", updated_by=updated_by
        )
        return {"status": "ok", "user_id": user_id, "topup_credit_balance": balance}

    async def set_topup_credits(
        self, *, user_id: str, value: int, reason: str, updated_by: str
    ) -> dict[str, Any]:
        balance = await self._admin_repo.set_topup_credits(
            user_id=user_id, value=int(value), reason=reason or "", updated_by=updated_by
        )
        return {"status": "ok", "user_id": user_id, "topup_credit_balance": balance}

    async def set_plan(self, *, user_id: str, plan: str) -> dict[str, Any]:
        allowed = set((config.billing.plan_credits or {}).keys())
        if allowed and plan not in allowed:
            raise SettingError(f"Unknown plan: {plan} (allowed: {', '.join(sorted(allowed))})")
        ok = await self._admin_repo.set_plan(user_id=user_id, plan=plan)
        # plan не входит в кэшируемый UserProfileLogic — инвалидация не требуется.
        return {"status": "ok", "user_id": user_id, "plan": plan, "updated": ok}

    async def set_active(
        self, *, user_id: str, is_active: bool, acting_admin_id: str
    ) -> dict[str, Any]:
        if not is_active:
            if str(user_id).lower() == str(acting_admin_id).lower():
                raise AdminRoleError("Cannot block yourself")
            if self.is_env_admin(user_id):
                raise AdminRoleError("Cannot block a bootstrap admin (SERVICE__ADMIN_USER_IDS)")
        user = await self._admin_repo.get_user(user_id=user_id)
        if user is None:
            raise ValueError("user not found")
        ok = await self._admin_repo.set_active(user_id=user_id, is_active=is_active)
        await self._invalidate_profile_cache(user_id, user.get("email"))
        return {"status": "ok", "user_id": user_id, "is_active": is_active, "updated": ok}

    # --- аналитика --------------------------------------------------------- #
    async def get_system_analytics(self, *, range_key: str = "30d") -> dict[str, Any]:
        """Системная аналитика: потребление + ФИНАНСЫ (P&L) + активность базы.

        Доход берётся из платёжных событий (`amount` в ₽), себестоимость — из
        `usage_daily.raw_cost_rub` (сколько реально ушло провайдеру), поэтому
        чистая прибыль честная: доход − возвраты − себестоимость.
        Старые ключи (series/by_model/by_agent/totals/abuse_flags/status)
        сохранены — панель аналитики их уже использует.
        """
        from service.services.billing.application.billing_service import shape_analytics

        days = _RANGE_DAYS.get(range_key, 30)
        since = (datetime.now(UTC) - timedelta(days=days)).date()
        prev_since = (datetime.now(UTC) - timedelta(days=days * 2)).date()

        repo = self._admin_repo
        (
            daily,
            events,
            flags,
            revenue_daily,
            cost_daily,
            new_users,
            hourly,
            weekday,
            user_totals,
            plans,
            sales,
            top_users,
            windows_rev,
            windows_cost,
            counts,
            prev_revenue_daily,
            prev_cost_daily,
        ) = await asyncio.gather(
            repo.fetch_usage_daily_all(since=since),
            repo.fetch_usage_events_all(since=since),
            repo.fetch_recent_flags(limit=50),
            repo.fetch_revenue_daily(since=since),
            repo.fetch_cost_daily(since=since),
            repo.fetch_new_users_daily(since=since),
            repo.fetch_activity_hourly(since=since),
            repo.fetch_activity_weekday(since=since),
            repo.fetch_user_totals(),
            repo.fetch_plan_distribution(),
            repo.fetch_sales_breakdown(since=since),
            repo.fetch_top_users(since=since, limit=12),
            repo.fetch_finance_windows(),
            repo.fetch_cost_windows(),
            repo.fetch_period_counts(since=since),
            repo.fetch_revenue_daily(since=prev_since),
            repo.fetch_cost_daily(since=prev_since),
        )

        finance = _build_finance(
            revenue_daily=revenue_daily,
            cost_daily=cost_daily,
            new_users=new_users,
            windows_rev=windows_rev,
            windows_cost=windows_cost,
            counts=counts,
            sales=sales,
            prev_revenue_daily=prev_revenue_daily,
            prev_cost_daily=prev_cost_daily,
            since=since,
        )
        plan_prices = dict(config.billing.plan_prices_rub or {})
        plans_out = [
            {
                **row,
                "price_rub": int(plan_prices.get(row["plan"], 0)),
                "mrr_rub": int(plan_prices.get(row["plan"], 0)) * int(row["users"]),
            }
            for row in plans
        ]
        finance["totals"]["mrr_rub"] = round(sum(p["mrr_rub"] for p in plans_out), 2)

        return {
            "range": range_key,
            **shape_analytics(daily, events),
            "abuse_flags": flags,
            "status": self._provider_status(),
            "finance": finance,
            "users": {
                "totals": user_totals,
                "plans": plans_out,
                "new_daily": [{"day": str(r["day"]), "count": r["count"]} for r in new_users],
                "activity_hourly": hourly,
                "activity_weekday": weekday,
                "top": [
                    {**u, "profit_rub": round(u["revenue_rub"] - u["cost_rub"], 2)}
                    for u in top_users
                ],
            },
        }

    @staticmethod
    def _provider_status() -> dict[str, Any]:
        # Кто настроен и кто активен — знает САЙДКАР (у него ключи и реестр). Берём из
        # уже посчитанного снимка здоровья: отдельный синхронный поход по сети ради
        # шапки панели того не стоит. Кэш пуст (панель ещё не открывали) — честно пусто.
        cached = _HEALTH_CACHE.get("data") or {}
        providers = {
            name: bool(info.get("configured"))
            for name, info in (cached.get("providers") or {}).items()
        }
        active = cached.get("active_provider")
        return {
            "active_provider": active,
            "providers_configured": providers,
            "failover_enabled": runtime_settings.get_agents(
                "provider_failover_enabled", config.agents.provider_failover_enabled
            ),
            "memory_provider": runtime_settings.get_agents(
                "memory_provider", config.agents.memory_provider
            ),
        }

    async def provider_health(self) -> dict[str, Any]:
        """Статус провайдеров БЕЗ живых проб на каждый показ (убрали постоянный пуллинг).

        Отдаём последний сохранённый снапшот. Обновляется он только по явной команде
        админа (кнопка «Проверить» → ``recheck_provider_health``) или разовым прогревом на
        старте — а не фоновым пересчётом на каждый устаревший запрос, как было раньше.
        Холодный старт (снапшота ещё нет) считает один раз.
        """
        import time

        cached = _HEALTH_CACHE["data"]
        if cached is not None:
            # disabled — чистая настройка, без сети, и отдавать её из снапшота НЕЛЬЗЯ:
            # снапшот делается только по кнопке «Проверить», поэтому чекбокс «сам
            # возвращался» к старому значению. Накладываем актуальный поверх кэша.
            return self._apply_disabled_overlay(cached)
        data = self._apply_disabled_overlay(await self._compute_provider_health())
        _HEALTH_CACHE.update(ts=time.monotonic(), data=data)
        return data

    @staticmethod
    def _apply_disabled_overlay(data: dict[str, Any]) -> dict[str, Any]:
        """Наложить АКТУАЛЬНЫЙ ``disabled`` (из настройки) на снапшот здоровья.

        Пробы (reachable/blocked/balance) остаются из кэша — они дорогие (сеть); а
        ``disabled`` берётся из настройки в реальном времени, поэтому тумблер провайдера
        отражается сразу, без перепроверки.
        """
        from service.infrastructure import provider_policy_store as provider_policy

        try:
            disabled = provider_policy.disabled_providers()
        except Exception:  # noqa: BLE001
            # Health information remains useful even if the optional runtime
            # setting cannot be read; only the fresh disabled overlay is lost.
            return _provider_health_status(data)
        providers = data.get("providers") or {}
        patched = {name: {**info, "disabled": name in disabled} for name, info in providers.items()}
        return _provider_health_status({**data, "providers": patched})

    async def recheck_provider_health(self) -> dict[str, Any]:
        """Живая проверка ВСЕХ провайдеров по кнопке админа + управление health-блоком.

        Пробит по-настоящему (force), игнорируя транзитный circuit_breaker: админ хочет
        знать реальное состояние. Итог: сконфигурированный, но недостижимый провайдер →
        ``provider_policy.set_blocked`` (persistent, скрыт у юзеров, не пробуется); снова
        достижимый → ``clear_blocked``. Снимок кладём в кэш для последующих показов.
        """
        import time

        from service.infrastructure import provider_policy_store as provider_policy

        data = self._apply_disabled_overlay(await self._compute_provider_health(force_probe=True))
        newly_blocked: set[str] = set()
        for name, info in (data.get("providers") or {}).items():
            if not info.get("configured"):
                info["blocked"] = False
                continue  # не настроен — не блокируем, просто нет клиента
            if info.get("disabled"):
                # Keep a previous breaker state intact: it becomes relevant
                # again if the operator later re-enables this provider.
                continue
            if info.get("reachable"):
                await provider_policy.clear_blocked(name)
                info["blocked"] = False
            else:
                reason = info.get("reason") or info.get("error") or "проверка не прошла"
                await provider_policy.set_blocked(name, str(reason))
                info["blocked"] = True  # патчим флаг без повторного пробинга
                newly_blocked.add(name)
        # Каскад: если заблокирован провайдер эмбеддера MemOS — переключить на фолбэк + вайп.
        # doc-vector самолечится в vector_store (фолбэк на следующем embed), memos — нет
        # hot-reload, поэтому переключаем настройку+вайпим здесь (применится после рестарта memos).
        if newly_blocked:
            await self._cascade_memos_embedder(newly_blocked)
        _HEALTH_CACHE.update(ts=time.monotonic(), data=data)
        return data

    async def _cascade_memos_embedder(self, blocked: set[str]) -> None:
        """Провайдер эмбеддера MemOS заблокирован → переключить на первый рабочий фолбэк + вайп.

        Полностью авто (по требованию): стабильность важнее сохранности памяти. Ограничение:
        memos читает эмбеддер на СТАРТЕ (нет hot-reload) — новый применится после рестарта
        контейнера memos; до этого память пуста/fail-open.
        """
        from service.infrastructure import provider_policy_store as provider_policy

        model = runtime_settings.get_agents(
            "memos_embedder_model", config.agents.memos_embedder_model
        )
        provider = str(model or "").partition(":")[0]
        if not provider or provider not in blocked:
            return
        fallback = (
            runtime_settings.get_agents(
                "memos_embedder_fallback", config.agents.memos_embedder_fallback
            )
            or []
        )
        unavailable = await provider_policy.unavailable_providers()
        for cand in fallback:
            if not isinstance(cand, dict) or not cand.get("model"):
                continue
            prov = str(cand["model"]).partition(":")[0]
            if prov and prov in unavailable:
                continue
            try:
                await self.set_setting(
                    "agents.memos_embedder_model", cand["model"], updated_by="cascade"
                )
                await self.set_setting(
                    "agents.memos_embedder_dim", int(cand.get("dim") or 1536), updated_by="cascade"
                )
                from service.infrastructure.memory.memos import wipe_memos_memory

                wipe = await wipe_memos_memory()
                logger.warning(
                    "MemOS-эмбеддер переключён на %s (провайдер '%s' заблокирован); память стёрта "
                    "(%s), требуется рестарт memos для применения",
                    cand["model"],
                    provider,
                    wipe,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Каскад смены эмбеддера MemOS не удался")
            return

    async def recheck_blocked_providers(self) -> dict[str, Any]:
        """Точечная самопроверка ТОЛЬКО заблокированных (для периодического celery-таска).

        Здоровых не трогает: проба в сайдкаре — настоящий вызов к провайдеру, поэтому
        спрашиваем поимённо. Блокировка persistent, так что это ЕДИНСТВЕННЫЙ автоматический
        путь обратно — иначе моргнувший однажды провайдер ждёт ручного «Проверить».

        🔴 Здесь стояла заглушка, безусловно возводившая `NotImplementedError` (пробу
        перенесли в сайдкар, вызов остался): задача падала на первом же заблокированном
        каждые 5 минут. Живой стек застали с тремя выключенными провайдерами из пяти.
        """
        from service.infrastructure import provider_policy_store as provider_policy
        from service.settings import config as _config

        blocked = sorted(await provider_policy.blocked_providers())
        if not blocked:
            return {"checked": [], "cleared": []}

        from service.infrastructure.agents_client.sidecar_providers import fetch_provider_health

        data = await fetch_provider_health(_config, force_probe=True, only=blocked)
        if data is None:
            # Сайдкар молчит — это не «провайдеры мертвы». Снимать блок не с чего, но и
            # молча считать проверку выполненной нельзя: иначе поломка связи выглядит
            # как «проверили, никто не ожил».
            logger.warning("самопроверка заблокированных: сервис агентов не ответил")
            return {"checked": blocked, "cleared": [], "unavailable": True}

        providers = data.get("providers") or {}
        cleared: list[str] = []
        for name in blocked:
            if (providers.get(name) or {}).get("reachable"):
                await provider_policy.clear_blocked(name)
                cleared.append(name)
        if cleared:
            logger.info("самопроверка: провайдеры снова доступны и разблокированы: %s", cleared)
        return {"checked": blocked, "cleared": cleared}

    async def _compute_provider_health(self, *, force_probe: bool = False) -> dict[str, Any]:
        """Сводка здоровья провайдеров: с сайдкара, если движок там; иначе — локально.

        В http-режиме провайдерам звонит САЙДКАР, поэтому мерить надо оттуда: локальная
        проба backend'а отвечает на другой вопрос, а его circuit_breaker после переезда
        трафика пуст и о реальных отказах не знает.

        Fail-open: сайдкар недоступен → считаем сами, как раньше. Панель не должна гаснуть
        из-за моргнувшего сайдкара, но и молчать об этом нельзя — пишем WARNING, иначе
        «здоровье не оттуда» осталось бы незаметным.
        """
        from service.infrastructure.agents_client.sidecar_providers import fetch_provider_health
        from service.settings import config as _config

        data = await fetch_provider_health(_config, force_probe=force_probe)
        if data is not None:
            return data
        # Локальной пробы больше нет: провайдерам звонит сайдкар, он же и меряет.
        # Показываем ЧЕСТНОЕ «не знаем», а не пустую таблицу, которую админ прочитает
        # как «все провайдеры мертвы» и пойдёт чинить исправное.
        logger.error("здоровье провайдеров недоступно: сервис агентов не отвечает")
        return {"active_provider": None, "providers": {}, "unavailable": True}

    async def prime_provider_health(self) -> None:
        """Прогреть кэш здоровья в фоне на старте приложения: тогда даже ПЕРВЫЙ показ
        панели мгновенен, а не ждёт живых проб. Fail-soft — старт не должен падать."""
        import time

        try:
            data = self._apply_disabled_overlay(await self._compute_provider_health())
            _HEALTH_CACHE.update(ts=time.monotonic(), data=data)
        except Exception:  # noqa: BLE001
            logger.debug("provider health prime failed", exc_info=True)
