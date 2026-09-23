"""Сервис кошельков и контроля кредитов (Фаза 3).

Два кошелька: подписочный (остаток активной квоты периода, сгорает) и
докупленный (user.topup_credit_balance, не сгорает). Списание идёт сначала с
подписки, затем с докупки. Free-тариф провизионится лениво при первом списании.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from service.services.billing.application.billing_period import month_period
from service.services.billing.application.cost_guard import (
    add_cost_guard_snapshot,
    cost_guard_metrics,
    record_charge_observability,
)
from service.services.billing.application.ports import PaymentWebhookError

logger = logging.getLogger(__name__)
_RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}
_TOP_REQUESTS = 5


@dataclass(frozen=True)
class Balance:
    plan: str
    subscription_remaining: int
    subscription_limit: int | None
    topup: int
    total: int
    reset_date: date | None


def _iso_day(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def compute_reconcile(totals: dict, *, credit_unit_rub: float, min_margin: float) -> dict[str, Any]:
    """Фактическая маржа на реальных данных: списанные кредиты × курс vs себестоимость.

    actual_margin ≈ billed/raw должна быть ≥ min_margin (иначе работаем в убыток).
    """
    credits = int(totals.get("credits", 0) or 0)
    raw = float(totals.get("raw_cost_rub", 0) or 0)
    billed = credits * float(credit_unit_rub)
    actual_margin = (billed / raw) if raw > 0 else None
    healthy = actual_margin is None or actual_margin >= float(min_margin)
    return {
        "credits": credits,
        "requests": int(totals.get("requests", 0) or 0),
        "raw_cost_rub": round(raw, 4),
        "billed_rub": round(billed, 4),
        "actual_margin": round(actual_margin, 3) if actual_margin is not None else None,
        "min_margin": float(min_margin),
        "healthy": healthy,
    }


def shape_analytics(daily: list[dict], events: list[dict]) -> dict[str, Any]:
    """Чистое преобразование сырых строк в данные для графиков UI.

    series — траты/запросы/токены по дням; by_model — разбивка по моделям (топ-8)
    с расщеплением prompt/completion токенов; by_agent — траты по типам операций
    (топ-8); top_requests — самые дорогие запросы; totals — сумма/среднее/пик.

    Старые события без prompt/completion в metadata обрабатываются мягко (0).
    raw_cost_rub/маржа сюда НЕ попадают — это внутренние поля, не для UI.
    """
    series = [
        {
            "day": _iso_day(row["day"]),
            "credits": int(row.get("credits", 0) or 0),
            "requests": int(row.get("requests", 0) or 0),
            "tokens": int(row.get("tokens", 0) or 0),
        }
        for row in daily
    ]

    by_model: dict[str, dict[str, int]] = {}
    by_agent: dict[str, int] = {}
    request_rows: list[dict[str, Any]] = []
    for event in events:
        meta = event.get("metadata") or {}
        credits = int(meta.get("credits", 0) or 0)
        prompt = int(meta.get("prompt", 0) or 0)
        completion = int(meta.get("completion", 0) or 0)
        tokens = int(event.get("tokens", 0) or 0)
        model = meta.get("model") or "unknown"

        bucket = by_model.setdefault(
            model,
            {"credits": 0, "prompt_tokens": 0, "completion_tokens": 0, "tokens": 0, "requests": 0},
        )
        bucket["credits"] += credits
        bucket["prompt_tokens"] += prompt
        bucket["completion_tokens"] += completion
        bucket["tokens"] += tokens
        bucket["requests"] += 1

        tools = meta.get("tools") or []
        agent = tools[0] if tools else "general"
        by_agent[agent] = by_agent.get(agent, 0) + credits

        request_rows.append(
            {
                "model": model,
                "credits": credits,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "tokens": tokens,
                "thread_id": meta.get("thread_id"),
            }
        )

    total_credits = sum(int(row.get("credits", 0) or 0) for row in daily)
    total_requests = sum(int(row.get("requests", 0) or 0) for row in daily)
    avg = (total_credits / total_requests) if total_requests else 0.0
    peak = max(daily, key=lambda row: row.get("credits", 0), default=None)

    by_model_out = [
        {"name": name, **stats}
        for name, stats in sorted(by_model.items(), key=lambda kv: kv[1]["credits"], reverse=True)[
            :8
        ]
    ]
    by_agent_out = [
        {"name": name, "credits": value}
        for name, value in sorted(by_agent.items(), key=lambda kv: kv[1], reverse=True)[:8]
    ]
    top_requests = sorted(
        (row for row in request_rows if row["credits"] > 0),
        key=lambda row: row["credits"],
        reverse=True,
    )[:_TOP_REQUESTS]

    return {
        "series": series,
        "by_model": by_model_out,
        "by_agent": by_agent_out,
        "top_requests": top_requests,
        "totals": {
            "credits": total_credits,
            "requests": total_requests,
            "avg_credits_per_request": round(avg, 1),
            "peak_day": _iso_day(peak["day"]) if peak else None,
        },
    }


class BillingService:
    def __init__(
        self, billing_repo: Any, billing_config: Any, payment_provider: Any | None = None
    ) -> None:
        self._repo = billing_repo
        self._cfg = billing_config
        self._payment_provider = payment_provider

    async def get_balance(self, user_id: str, *, today: date | None = None) -> Balance:
        today = today or date.today()
        free = int(self._cfg.free_plan_credits)
        row = await self._repo.get_balance(user_id=str(user_id))

        if row is None:
            # пользователя нет в БД (аноним/несохранённый) — считаем как свежий free
            _, reset = month_period(today)
            return Balance("free", free, None, 0, free, reset)

        plan = row.get("plan") or "free"
        topup = int(row.get("topup") or 0)
        limit = row.get("limit")
        used = row.get("used")

        if limit is not None:
            sub_remaining = max(0, int(limit) - int(used or 0))
            sub_limit: int | None = int(limit)
            reset = row.get("period_end")
        else:
            # активной квоты нет — доступен бесплатный месячный пакет (ещё не провизионен)
            sub_remaining = free
            sub_limit = None
            _, reset = month_period(today)

        return Balance(plan, sub_remaining, sub_limit, topup, sub_remaining + topup, reset)

    async def has_sufficient_credits(self, user_id: str, *, today: date | None = None) -> bool:
        balance = await self.get_balance(user_id, today=today)
        return balance.total > 0

    async def reserve(
        self, user_id: str, *, credits: int, ttl_seconds: int = 600, today: date | None = None
    ) -> str | None:
        """Удержать кредиты до вызова LLM; резерв закрывает гонку конкурентных запросов."""
        today = today or date.today()
        period_start, period_end = month_period(today)
        reservation_id = await self._repo.reserve(
            user_id=str(user_id),
            credits=int(credits),
            ttl_seconds=int(ttl_seconds),
            free_plan_credits=int(self._cfg.free_plan_credits),
            period_start=period_start,
            period_end=period_end,
        )
        if reservation_id:
            cost_guard_metrics.reservation("created")
        return reservation_id

    async def release_reservation(self, reservation_id: str) -> None:
        """Отпустить резерв без списания (job не выставлен в счёт / ошибка до чарджа)."""
        await self._repo.release_reservation(reservation_id=str(reservation_id))
        cost_guard_metrics.reservation("released")

    async def refund(self, user_id: str, *, credits: int, reason: str) -> None:
        """Вернуть ранее списанные кредиты (job упал уже ПОСЛЕ успешного charge())."""
        await self._repo.refund(user_id=str(user_id), credits=int(credits), reason=reason)

    async def charge(
        self,
        user_id: str,
        *,
        credits: int,
        tokens: int,
        raw_cost_rub: float,
        metadata: dict[str, Any] | None = None,
        today: date | None = None,
        reservation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Списать кредиты (подписка→докупка) и записать потребление.

        Если передан ``reservation_id`` — соответствующий резерв атомарно
        помечается committed в той же транзакции, что и списание. Если передан
        ``idempotency_key`` (обычно ``job_id``) и за него уже списывали —
        повторного списания не будет (защита от редоставки Celery-задачи), метод
        вернёт ``{"idempotent": True, ...}``.
        """
        today = today or date.today()
        period_start, period_end = month_period(today)
        result = await self._repo.charge(
            user_id=str(user_id),
            credits=int(credits),
            tokens=int(tokens),
            raw_cost_rub=float(raw_cost_rub),
            free_plan_credits=int(self._cfg.free_plan_credits),
            period_start=period_start,
            period_end=period_end,
            metadata=metadata,
            reservation_id=reservation_id,
            idempotency_key=idempotency_key,
        )
        record_charge_observability(reservation_id=reservation_id, result=result, metadata=metadata)
        return result

    # --- платежи (Фаза 4) ------------------------------------------------- #
    def list_plans_and_packs(self) -> dict[str, Any]:
        plans = [
            {
                "id": name,
                "credits": int(credits),
                "price_rub": int((self._cfg.plan_prices_rub or {}).get(name, 0)),
            }
            for name, credits in (self._cfg.plan_credits or {}).items()
        ]
        packs = [dict(pack) for pack in (self._cfg.topup_packs or [])]
        return {"plans": plans, "packs": packs}

    def _find_pack(self, pack_id: str | None) -> dict[str, Any] | None:
        for pack in self._cfg.topup_packs or []:
            if str(pack.get("id")) == str(pack_id):
                return pack
        return None

    async def create_checkout(
        self, *, user_id: str, kind: str, plan: str | None = None, pack_id: str | None = None
    ) -> dict[str, Any]:
        """Создать сессию оплаты. Возвращает {checkout_url, confirmation_token}:
        redirect-провайдеры дают checkout_url (фронт делает redirect), embedded
        (ЮKassa) — confirmation_token (фронт инициализирует виджет)."""
        if self._payment_provider is None:
            raise PaymentWebhookError("Payments are not configured")

        if kind == "subscription":
            if not plan or plan not in (self._cfg.plan_credits or {}):
                raise ValueError("Unknown plan")
            amount = float((self._cfg.plan_prices_rub or {}).get(plan, 0))
            description = f"Подписка {plan}"
            metadata = {"kind": "subscription", "plan": plan, "user_id": str(user_id)}
        elif kind == "topup":
            pack = self._find_pack(pack_id)
            if not pack:
                raise ValueError("Unknown pack")
            amount = float(pack["price_rub"])
            description = f"Докупка {pack['credits']} кредитов"
            metadata = {"kind": "topup", "pack_id": pack_id, "user_id": str(user_id)}
        else:
            raise ValueError("Unknown checkout kind")

        # Бесплатный/нулевой тариф не оформляется через оплату: ЮKassa отклоняет
        # платёж на 0 ₽ (её 400 уходил в 500), а «покупка free» ещё и обнуляла бы
        # used бесплатной квоты. free выдаётся лениво при первом списании.
        if amount <= 0:
            raise ValueError("Этот тариф нельзя оформить через оплату")

        # Email нужен провайдеру для customer.email в фискальном чеке (54-ФЗ): ЮKassa
        # шлёт чек на него. Best-effort — сбой чтения не должен ронять оформление оплаты.
        customer_email: str | None = None
        try:
            get_email = getattr(self._repo, "get_user_email", None)
            if get_email is not None:
                customer_email = await get_email(user_id=str(user_id))
        except Exception:
            logger.exception("Failed to fetch email for checkout receipt (user %s)", user_id)

        result = await self._payment_provider.create_checkout(
            user_id=str(user_id),
            amount_rub=amount,
            description=description,
            kind=kind,
            metadata=metadata,
            customer_email=customer_email,
        )
        # Запоминаем инициированный платёж — если вебхук не дойдёт, сверка
        # (reconcile_pending_payments) перепроверит статус по API и до-начислит.
        # Не критично для checkout: при сбое записи оплата всё равно пройдёт по
        # вебхуку, поэтому ошибку глушим.
        record_pending = getattr(self._repo, "record_pending_payment", None)
        if record_pending is not None and result.provider_ref:
            try:
                await record_pending(
                    payment_id=str(result.provider_ref),
                    user_id=str(user_id),
                    kind=kind,
                    plan=plan,
                    pack_id=pack_id,
                )
            except Exception:
                logger.exception("Failed to record pending payment %s", result.provider_ref)
        return {
            "checkout_url": result.redirect_url or None,
            "confirmation_token": result.confirmation_token,
            "provider_ref": result.provider_ref,
        }

    def _resolve_grant(self, event: Any) -> dict[str, Any] | None:
        """Вывести начисление из события по конфигу (НЕ доверяя клиенту)."""
        if event.type != "payment.succeeded":
            return None
        if event.kind == "subscription" and event.plan:
            credits = int((self._cfg.plan_credits or {}).get(event.plan, 0))
            if credits <= 0:
                return None
            return {
                "kind": "subscription",
                "plan": event.plan,
                "credits": credits,
                "amount_rub": float((self._cfg.plan_prices_rub or {}).get(event.plan, 0)),
                "currency": event.currency,
                "provider_ref": event.raw.get("subscription_id"),
            }
        if event.kind == "topup" and event.pack_id:
            pack = self._find_pack(event.pack_id)
            if not pack:
                return None
            return {
                "kind": "topup",
                "pack_id": event.pack_id,
                "credits": int(pack["credits"]),
                "amount_rub": float(pack["price_rub"]),
                "currency": event.currency,
            }
        return None

    async def handle_webhook(
        self, *, raw_body: bytes, headers: dict[str, str], today: date | None = None
    ) -> dict[str, Any]:
        """Проверить подпись, идемпотентно применить платёж или возврат."""
        if self._payment_provider is None:
            raise PaymentWebhookError("Payments are not configured")
        event = self._payment_provider.verify_webhook(raw_body=raw_body, headers=headers)

        # Возврат платежа → откат кредитов. payment.canceled (незавершённый платёж)
        # начислять/откатывать нечего — уходит в _resolve_grant → ignored.
        if str(event.type or "").startswith("refund."):
            return await self._handle_refund(event)

        # Если провайдер умеет — заменяем kind/plan/pack_id/user_id/сумму из
        # (недоверенного) тела вебхука на authoritative-данные, полученные по API
        # для этого payment_id (анти-подделка вебхука: тело POST ничем не подписано).
        fetch_authoritative = getattr(self._payment_provider, "fetch_authoritative_event", None)
        if fetch_authoritative is not None:
            authoritative = await fetch_authoritative(event.id)
            if authoritative is None:
                return {"status": "unconfirmed"}
            event = authoritative
        else:
            # Провайдер без authoritative-переполучения (например, старый confirm_succeeded-
            # only дак-тайп в тестах) — перепроверяем статус, но продолжаем доверять телу.
            confirm = getattr(self._payment_provider, "confirm_succeeded", None)
            if confirm is not None and not await confirm(event.id):
                return {"status": "unconfirmed"}

        grant = self._resolve_grant(event)
        if grant is None:
            return {"status": "ignored"}
        # Платная подписка = скользящие N дней от даты оплаты (не календарный месяц).
        period_days = int(getattr(self._cfg, "subscription_period_days", 30) or 30)
        res = await self._repo.apply_webhook(
            webhook_id=event.id,
            event_type=event.type,
            payload=event.raw,
            user_id=event.user_id,
            grant=grant,
            period_days=period_days,
        )
        # Письмо-подтверждение — только на НОВОМ начислении (не на повторе вебхука).
        if res.get("status") == "ok":
            await self._notify_payment_succeeded(event, grant)
        # Снимаем платёж с очереди сверки (вебхук успел — пересверять не нужно).
        await self._mark_payment_reconciled(event.id)
        return res

    async def _mark_payment_reconciled(self, payment_id: str) -> None:
        mark = getattr(self._repo, "set_payment_status", None)
        if mark is None:
            return
        try:
            await mark(payment_id=str(payment_id), status="reconciled")
        except Exception:
            logger.exception("Failed to mark payment %s reconciled", payment_id)

    async def _notify_payment_succeeded(self, event: Any, grant: dict[str, Any]) -> None:
        """Поставить в очередь брендовое письмо об успешной оплате (best-effort).

        Вызывается ТОЛЬКО на новом начислении (apply_webhook → status="ok"), поэтому
        повтор вебхука письмо не дублирует. Наше письмо — дополнение к фискальному чеку
        ЮKassa; сбой отправки не должен влиять на уже применённый платёж.
        """
        try:
            get_email = getattr(self._repo, "get_user_email", None)
            email = await get_email(user_id=str(event.user_id)) if get_email else None
            if not email:
                return
            from service.infrastructure.messaging import tasks

            await asyncio.to_thread(
                tasks.send_payment_receipt_email.delay,
                email,
                int(grant.get("credits", 0) or 0),
                float(grant.get("amount_rub", 0) or 0),
                grant.get("plan"),
            )
        except Exception:
            logger.exception("Failed to enqueue payment receipt email for %s", event.user_id)

    async def reconcile_pending_payments(
        self, *, older_than_min: int = 15, window_hours: int = 48, limit: int = 100
    ) -> dict[str, Any]:
        """Досверить платежи, по которым вебхук мог не дойти.

        Для каждого зависшего pending перезапрашиваем статус по API провайдера
        (authoritative). succeeded, но ещё не начислен → apply_webhook (идемпотентно
        по payment_id) + помечаем reconciled. Не-succeeded в окне оставляем pending
        (вебхук/оплата ещё возможны); выпавшие из окна SQL уже не отдаёт.
        """
        if self._payment_provider is None:
            return {"status": "no_provider"}
        fetch_authoritative = getattr(self._payment_provider, "fetch_authoritative_event", None)
        if fetch_authoritative is None:
            # mock/dev без authoritative-переполучения — сверять нечем.
            return {"status": "unsupported"}

        pendings = await self._repo.fetch_stale_pending_payments(
            older_than_min=older_than_min, window_hours=window_hours, limit=limit
        )
        reconciled = 0
        period_days = int(getattr(self._cfg, "subscription_period_days", 30) or 30)
        for pending in pendings:
            payment_id = pending["payment_id"]
            try:
                event = await fetch_authoritative(payment_id)
                if event is None:
                    continue  # ещё не succeeded — ждём, статус не трогаем
                grant = self._resolve_grant(event)
                if grant is None:
                    continue
                res = await self._repo.apply_webhook(
                    webhook_id=event.id,
                    event_type=event.type,
                    payload=event.raw,
                    user_id=event.user_id,
                    grant=grant,
                    period_days=period_days,
                )
                await self._repo.set_payment_status(payment_id=payment_id, status="reconciled")
                # Письмо только если начисление реально новое (вебхук мог успеть раньше).
                if res.get("status") == "ok":
                    await self._notify_payment_succeeded(event, grant)
                reconciled += 1
                logger.warning("Reconciled lost payment %s (webhook never arrived)", payment_id)
            except Exception:
                logger.exception("Reconcile failed for payment %s", payment_id)
        return {"status": "ok", "checked": len(pendings), "reconciled": reconciled}

    async def _handle_refund(self, event: Any) -> dict[str, Any]:
        """Откат кредитов по возврату платежа (см. apply_refund в репозитории)."""
        fetch_refund = getattr(self._payment_provider, "fetch_authoritative_refund", None)
        if fetch_refund is not None:
            # yookassa: authoritative-данные возврата по API (тело не на веру).
            refund = await fetch_refund(event.id)
            if refund is None:
                return {"status": "unconfirmed"}
            refund_id = refund.id
            payment_id = refund.payment_id
            amount_rub = refund.amount_rub
            raw = refund.raw
        else:
            # mock/dev: подпись уже проверена verify_webhook при заданном секрете;
            # payment_id берём из тела (object.payment_id или payment_id).
            body = event.raw or {}
            obj = body.get("object") if isinstance(body.get("object"), dict) else {}
            payment_id = str(obj.get("payment_id") or body.get("payment_id") or "")
            refund_id = event.id
            amount_rub = event.amount_rub
            raw = body

        if not payment_id:
            return {"status": "ignored"}

        return await self._repo.apply_refund(
            refund_id=str(refund_id),
            source_payment_id=str(payment_id),
            event_type=str(event.type),
            payload=raw,
            amount_rub=float(amount_rub or 0),
        )

    async def get_usage_analytics(
        self, user_id: str, *, range_key: str = "30d", today: date | None = None
    ) -> dict[str, Any]:
        today = today or date.today()
        days = _RANGE_DAYS.get(range_key, 30)
        since = today - timedelta(days=days)
        daily = await self._repo.fetch_usage_daily(user_id=str(user_id), since=since)
        events = await self._repo.fetch_usage_events(user_id=str(user_id), since=since)
        shaped = shape_analytics(daily, events)
        # Курс кредит→₽ для UI (billed ₽ = credits × credit_unit_rub). getattr —
        # чтобы SimpleNamespace-конфиг в тестах не падал; raw_cost/маржа НЕ отдаём.
        shaped["totals"]["credit_unit_rub"] = getattr(self._cfg, "credit_unit_rub", None)
        return {"range": range_key, **shaped}

    # Категории фильтра истории → множества event_type (белый список: значения
    # приходят из query-параметра, в SQL идут только известные типы).
    HISTORY_FILTERS: dict[str, list[str]] = {
        "usage": ["usage"],
        "topup": ["topup"],
        "subscription": ["subscription_grant"],
        "refund": ["refund"],
        "adjustment": ["adjustment", "admin_adjust"],
    }

    async def get_history(
        self,
        user_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
        kind: str | None = None,
    ) -> dict[str, Any]:
        """Страница истории операций + total (пагинация на сервере).

        Фильтр по категории тоже серверный: иначе «Списания» показывали бы лишь
        те, что попали в загруженную страницу, а не все за всё время.
        """
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        types = self.HISTORY_FILTERS.get(kind or "") if kind and kind != "all" else None
        events, total = await self._repo.fetch_events_page(
            user_id=str(user_id), limit=limit, offset=offset, types=types
        )
        return {"events": events, "total": total, "limit": limit, "offset": offset}

    # --- админ: управление ценами + сверка маржи -------------------------- #
    async def list_pricing(self) -> dict[str, Any]:
        """Список цен для админки: явные цены + весь чат-каталог, и для КАЖДОЙ модели —
        эффективная цена (что реально спишется), её источник и провайдер. Так ни одна
        модель не выглядит «нетарифицируемой»: нет явной цены → показываем цену класса
        или дефолт (они ненулевые). Не-чат модели (эмбеддеры/аудио/картинки) в каталог
        не попадают — их и выбрать в чате нельзя."""
        from decimal import Decimal

        from service.services.billing.application.pricing_service import classify_model
        from service.services.billing.domain.pricing import ModelPrice, resolve_model_price

        rows = await self._repo.list_pricing()
        from service.services.billing.application.pricing_freshness import pricing_sync_status

        sync_status = pricing_sync_status(rows)
        registry: dict[object, ModelPrice] = {}
        by_id: dict[tuple[str, str], dict] = {}
        for r in rows:
            mid = r.get("model_id") or ""
            provider = str(r.get("provider") or "").lower()
            by_id[(provider, mid)] = r
            pin = float(r.get("price_in_rub_per_1k") or 0)
            pout = float(r.get("price_out_rub_per_1k") or 0)
            # 0/0 трактуем как «не задано» (см. resolve_model_price) — такая модель
            # всё равно биллится по классу/дефолту, а не в ноль.
            r["priced"] = r.get("price_in_rub_per_1k") is not None and (pin > 0 or pout > 0)
            if r["priced"]:
                registry[(provider, mid)] = ModelPrice(
                    price_in_rub_per_1k=Decimal(str(r.get("price_in_rub_per_1k") or 0)),
                    price_out_rub_per_1k=Decimal(str(r.get("price_out_rub_per_1k") or 0)),
                )
            if not r.get("model_class"):
                r["model_class"] = classify_model(mid)

        # Параметры fallback из конфига (зеркалит PricingService).
        cfg = self._cfg
        default_price = ModelPrice(
            price_in_rub_per_1k=Decimal(str(cfg.default_price_in_rub_per_1k)),
            price_out_rub_per_1k=Decimal(str(cfg.default_price_out_rub_per_1k)),
        )
        class_prices: dict[str, ModelPrice] = {}
        for name, pair in (cfg.class_prices_rub_per_1k or {}).items():
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                class_prices[name] = ModelPrice(
                    price_in_rub_per_1k=Decimal(str(pair[0])),
                    price_out_rub_per_1k=Decimal(str(pair[1])),
                )

        # Каталог ТОЛЬКО чат-моделей + владелец-провайдер. Best-effort: сбой не ломает.
        # В http-режиме каталог знает САЙДКАР (он владеет мультипровайдерным слоем и
        # ходит в /models провайдеров); backend спрашивает его по HTTP, а при недоступности
        # считает по-старому — прайс-лист не должен схлопываться из-за моргнувшего сайдкара.
        try:
            from service.infrastructure.agents_client.sidecar_providers import (
                fetch_chat_model_catalog,
            )
            from service.settings import config as _cfg

            fetched = await fetch_chat_model_catalog(_cfg)
            # Каталога нет — прайс покажет только те модели, у которых цена задана явно.
            # Это лучше, чем выдумывать список: пустые строки в прайсе объяснимы, а
            # неверные — нет.
            catalog, owners = fetched if fetched is not None else ([], {})
        except Exception:  # noqa: BLE001
            catalog, owners = [], {}

        for mid in catalog:
            provider = str(owners.get(mid) or "").lower()
            if not mid or (provider, mid) in by_id:
                continue
            row = {
                "provider": provider or None,
                "model_id": mid,
                "price_in_rub_per_1k": None,
                "price_out_rub_per_1k": None,
                "margin_override": None,
                "model_class": classify_model(mid),
                "priced": False,
            }
            by_id[(provider, mid)] = row
            rows.append(row)

        # Эффективная цена + источник + провайдер для каждой строки.
        for r in rows:
            mid = r["model_id"]
            provider = str(r.get("provider") or owners.get(mid) or "").lower()
            eff = resolve_model_price(
                mid,
                registry=registry,
                provider=provider,
                classify=classify_model,
                class_prices=class_prices,
                default_price=default_price,
            )
            r["effective_in_rub_per_1k"] = float(eff.price_in_rub_per_1k)
            r["effective_out_rub_per_1k"] = float(eff.price_out_rub_per_1k)
            if (provider, mid) in registry or ("", mid) in registry:
                r["price_source"] = "explicit"
            else:
                cls = r.get("model_class")
                r["price_source"] = "class" if cls and cls in class_prices else "default"
            r["provider"] = provider or None

        return {"pricing": rows, "pricing_sync": sync_status}

    async def set_pricing(
        self,
        *,
        provider: str = "",
        model_id: str,
        price_in: float,
        price_out: float,
        margin_override: float | None = None,
        model_class: str | None = None,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        await self._repo.upsert_model_pricing(
            provider=provider,
            model_id=model_id,
            price_in=price_in,
            price_out=price_out,
            margin_override=margin_override,
            model_class=model_class,
            updated_by=updated_by,
        )
        return {"status": "ok", "provider": provider or None, "model_id": model_id}

    async def delete_pricing(self, *, model_id: str, provider: str = "") -> dict[str, Any]:
        deleted = await self._repo.delete_model_pricing(model_id=model_id, provider=provider)
        return {
            "status": "ok",
            "provider": provider or None,
            "model_id": model_id,
            "deleted": deleted,
        }

    async def reconcile(
        self, *, range_key: str = "30d", today: date | None = None
    ) -> dict[str, Any]:
        today = today or date.today()
        days = _RANGE_DAYS.get(range_key, 30)
        since = today - timedelta(days=days)
        totals = await self._repo.fetch_usage_totals(since=since)
        result = {
            "range": range_key,
            **compute_reconcile(
                totals,
                credit_unit_rub=self._cfg.credit_unit_rub,
                min_margin=self._cfg.min_margin,
            ),
        }
        await add_cost_guard_snapshot(
            repo=self._repo,
            result=result,
            warning_events=getattr(self._cfg, "cost_guard_warning_events", 1),
            critical_events=getattr(self._cfg, "cost_guard_critical_events", 5),
        )
        return result
