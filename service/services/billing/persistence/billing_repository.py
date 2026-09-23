from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.billing.domain.charge_math import split_charge
from service.services.billing.persistence.mixins import (
    CostEvents,
    EventHistory,
    PricingSync,
    ResMaint,
)
from service.services.billing.persistence.sql import (
    _ACTIVE_QUOTA_FOR_UPDATE_SQL,
    _ACTIVE_REMAINING_SQL,
    _ADD_TOPUP_SQL,
    _BALANCE_SQL,
    _CLAWBACK_QUOTA_SQL,
    _CLAWBACK_TOPUP_SQL,
    _COMMIT_RESERVATION_SQL,
    _DEDUCT_SUBSCRIPTION_SQL,
    _DEDUCT_TOPUP_SQL,
    _EXTEND_QUOTA_SQL,
    _FETCH_STALE_PENDING_SQL,
    _FIND_GRANT_BY_PAYMENT_SQL,
    _INSERT_PAID_QUOTA_SQL,
    _INSERT_PAYMENT_EVENT_SQL,
    _INSERT_PENDING_PAYMENT_SQL,
    _INSERT_REFUND_EVENT_SQL,
    _INSERT_RESERVATION_SQL,
    _INSERT_USAGE_EVENT_SQL,
    _LIST_PRICING_SQL,
    _PROVISION_QUOTA_SQL,
    _RECORD_WEBHOOK_SQL,
    _REFUND_TOPUP_SQL,
    _RELEASE_RESERVATION_SQL,
    _SET_PAYMENT_STATUS_SQL,
    _SET_PLAN_SQL,
    _SUM_ACTIVE_RESERVATIONS_SQL,
    _TOPUP_BALANCE_FOR_UPDATE_SQL,
    _TOPUP_BALANCE_SQL,
    _UPSERT_PRICING_SQL,
    _UPSERT_USAGE_DAILY_SQL,
    _USAGE_DAILY_RANGE_SQL,
    _USAGE_EVENT_EXISTS_SQL,
    _USAGE_EVENTS_RANGE_SQL,
    _USER_EMAIL_SQL,
    _WEBHOOK_EXISTS_SQL,
)
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

logger = logging.getLogger(__name__)


class BillingRepository(CostEvents, EventHistory, ResMaint, PricingSync, BaseRepository):
    """Доступ к billing-таблицам (схема ``profile``).

    Запись событий, резервирование и списание выполняются атомарно через SQL.
    """

    @connection()
    async def record_usage(
        self,
        *,
        user_id: str,
        tokens: int,
        credits: int,
        raw_cost_rub: float,
        metadata: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        """Записать потребление с кредитами (Фаза 2): событие + суточный агрегат.

        Обе вставки — в одной сессии/транзакции (атомарно). Кредиты и
        себестоимость кладутся в metadata события (для reconcile) и в
        usage_daily (для аналитики). По-прежнему read-only по балансам:
        списания/квот здесь нет — это появится в Фазе 3.
        """
        session = require_session(session)
        event_metadata = {
            **(metadata or {}),
            "credits": int(credits),
            "raw_cost_rub": float(raw_cost_rub),
        }
        await session.execute(
            text(_INSERT_USAGE_EVENT_SQL),
            {
                "user_id": str(user_id),
                "event_type": "usage",
                "tokens": int(tokens),
                "metadata": json.dumps(event_metadata, ensure_ascii=False),
            },
        )
        await session.execute(
            text(_UPSERT_USAGE_DAILY_SQL),
            {
                "user_id": str(user_id),
                "tokens": int(tokens),
                "credits": int(credits),
                "raw_cost": float(raw_cost_rub),
            },
        )
        logger.debug("Recorded usage: user=%s tokens=%s credits=%s", user_id, tokens, credits)

    @connection()
    async def get_balance(
        self, *, user_id: str, session: AsyncSession | None = None
    ) -> dict[str, Any] | None:
        """Сырые данные баланса: тариф, докуп-кошелёк, активная квота периода.

        Возвращает None, если пользователя нет в БД. Если активной квоты нет,
        поля limit/used/period_end будут None (новый free-юзер — лимит ещё не
        провизионился). Шейпинг в Balance делает BillingService.
        """
        session = require_session(session)
        result = await session.execute(text(_BALANCE_SQL), {"user_id": str(user_id)})
        row = result.first()
        if row is None:
            return None
        return {
            "plan": row[0],
            "topup": int(row[1] or 0),
            "limit": row[2],
            "used": row[3],
            "period_end": row[4],
        }

    @connection()
    async def get_user_email(
        self, *, user_id: str, session: AsyncSession | None = None
    ) -> str | None:
        """Email пользователя (для customer.email в чеке и письма об оплате). None, если нет."""
        session = require_session(session)
        row = (await session.execute(text(_USER_EMAIL_SQL), {"user_id": str(user_id)})).first()
        email = row[0] if row else None
        return str(email) if email else None

    @connection()
    async def reserve(
        self,
        *,
        user_id: str,
        credits: int,
        ttl_seconds: int,
        free_plan_credits: int,
        period_start,
        period_end,
        session: AsyncSession | None = None,
    ) -> str | None:
        """Атомарно удержать ``credits`` кредитов на ``ttl_seconds``, либо None при нехватке.

        Закрывает TOCTOU-гонку precheck'а: раньше проверка "баланс > 0" и реальное
        списание были разнесены по времени (баланс читался ДО дорогого вызова
        LLM), поэтому N параллельных запросов проходили один и тот же precheck
        и все успевали дойти до провайдера, хотя реального баланса хватало на
        один. Здесь то же самое чтение остатка квоты ``FOR UPDATE`` (что и в
        ``charge()``), поэтому конкурентные ``reserve()``/``charge()`` одного
        пользователя сериализуются на этой блокировке строки — второй вызов в
        очереди уже увидит резерв первого.
        """
        session = require_session(session)
        credits = max(0, int(credits))

        await session.execute(
            text(_PROVISION_QUOTA_SQL),
            {
                "user_id": str(user_id),
                "period_start": period_start,
                "period_end": period_end,
                "limit": int(free_plan_credits),
            },
        )

        remaining_res = await session.execute(
            text(_ACTIVE_REMAINING_SQL), {"user_id": str(user_id)}
        )
        remaining_row = remaining_res.first()
        remaining = int(remaining_row[0]) if remaining_row and remaining_row[0] is not None else 0

        topup_res = await session.execute(text(_TOPUP_BALANCE_SQL), {"user_id": str(user_id)})
        topup_row = topup_res.first()
        topup = int(topup_row[0]) if topup_row and topup_row[0] is not None else 0

        active_res = await session.execute(
            text(_SUM_ACTIVE_RESERVATIONS_SQL), {"user_id": str(user_id)}
        )
        active_row = active_res.first()
        active_reserved = int(active_row[0]) if active_row and active_row[0] is not None else 0

        available = max(0, remaining) + topup - active_reserved
        if available < credits:
            return None

        reservation_id = str(uuid4())
        await session.execute(
            text(_INSERT_RESERVATION_SQL),
            {
                "rid": reservation_id,
                "user_id": str(user_id),
                "amount": credits,
                "expires_at": datetime.now(UTC) + timedelta(seconds=int(ttl_seconds)),
            },
        )
        return reservation_id

    @connection()
    async def release_reservation(
        self, *, reservation_id: str, session: AsyncSession | None = None
    ) -> None:
        """Отпустить неиспользованный резерв (job не был выставлен в счёт)."""
        session = require_session(session)
        await session.execute(text(_RELEASE_RESERVATION_SQL), {"rid": reservation_id})

    @connection()
    async def charge(
        self,
        *,
        user_id: str,
        credits: int,
        tokens: int,
        raw_cost_rub: float,
        free_plan_credits: int,
        period_start,
        period_end,
        metadata: dict[str, Any] | None = None,
        reservation_id: str | None = None,
        idempotency_key: str | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Списать кредиты (подписка → докупка) и записать потребление атомарно.

        Порядок (одна транзакция): провизионим квоту периода при отсутствии →
        читаем остаток подписки (FOR UPDATE) → [идемпотентность: если за этот
        ``idempotency_key`` уже списывали — выходим без повторного списания] →
        списываем сначала с подписки, остаток с докуп-кошелька → пишем
        billing_event + usage_daily. Баланс может уйти в ноль, но не ниже
        (GREATEST). Возвращает фактическое распределение списания; при
        идемпотентном пропуске — ``{"idempotent": True, ...нули}``.
        """
        session = require_session(session)
        credits = int(credits)

        await session.execute(
            text(_PROVISION_QUOTA_SQL),
            {
                "user_id": str(user_id),
                "period_start": period_start,
                "period_end": period_end,
                "limit": int(free_plan_credits),
            },
        )

        remaining_res = await session.execute(
            text(_ACTIVE_REMAINING_SQL), {"user_id": str(user_id)}
        )
        remaining_row = remaining_res.first()
        remaining = int(remaining_row[0]) if remaining_row and remaining_row[0] is not None else 0

        # Есть usage-событие с этим ключом → это переотправка Celery-задачи, повторно не
        # списываем. Резерв ЭТОЙ попытки отпускаем (оригинал закоммитил свой), иначе он
        # зря держал бы баланс до истечения TTL.
        if idempotency_key:
            dup = (
                await session.execute(
                    text(_USAGE_EVENT_EXISTS_SQL),
                    {"user_id": str(user_id), "idem_key": str(idempotency_key)},
                )
            ).first()
            if dup is not None:
                if reservation_id:
                    await session.execute(text(_RELEASE_RESERVATION_SQL), {"rid": reservation_id})
                return {"from_subscription": 0, "from_topup": 0, "idempotent": True}

        # Распределение — доменное правило; остаток докупа читаем под блокировкой строки,
        # иначе два параллельных списания сочли бы его своим.
        topup_available = 0
        if credits > max(0, remaining):  # квоты не хватает — понадобится докуп
            topup_row = (
                await session.execute(
                    text(_TOPUP_BALANCE_FOR_UPDATE_SQL), {"user_id": str(user_id)}
                )
            ).first()
            topup_available = int(topup_row[0]) if topup_row and topup_row[0] is not None else 0

        split = split_charge(credits, remaining, topup_available)
        from_subscription, from_topup = split.from_subscription, split.from_topup
        if split.uncovered > 0:
            logger.warning(
                "СПИСАНО МЕНЬШЕ СТОИМОСТИ: запрошено %d, снято %d, НЕ ПОКРЫТО %d — "
                "разницу заплатила платформа",
                credits,
                split.total,
                split.uncovered,
            )

        if from_subscription > 0:
            await session.execute(
                text(_DEDUCT_SUBSCRIPTION_SQL),
                {"user_id": str(user_id), "amt": from_subscription},
            )
        if from_topup > 0:
            await session.execute(
                text(_DEDUCT_TOPUP_SQL), {"user_id": str(user_id), "amt": from_topup}
            )

        event_metadata = {
            **(metadata or {}),
            "credits": credits,
            "raw_cost_rub": float(raw_cost_rub),
            "from_subscription": from_subscription,
            "from_topup": from_topup,
        }
        # 🔴 НЕДОБОР ОСТАЁТСЯ В ИСТОРИИ, А НЕ ТОЛЬКО В ЛОГЕ. «Списали меньше стоимости» —
        # это деньги, которые заплатила платформа, и разбираться с ними приходится ПОСТФАКТУМ:
        # логи ротируются, а событие живёт. Замер по 579 списаниям dev-базы: 3 с недобором на
        # 1200 кредитов, самое дорогое списание 22 751 — и восстановить по истории, сколько
        # именно не покрыто, было НЕЧЕМ, приходилось считать разницу полей вручную.
        #
        # ⚠️ Пишем ТОЛЬКО когда недобор есть: поле-ноль у 99.5% событий ничего не добавляет,
        # а искать по нему станет труднее.
        if split.uncovered > 0:
            event_metadata["uncovered"] = split.uncovered
        if idempotency_key:
            # Ключ идемпотентности хранится в metadata события, чтобы повторная
            # (редоставленная) попытка нашла его через _USAGE_EVENT_EXISTS_SQL.
            event_metadata["idempotency_key"] = str(idempotency_key)
        await session.execute(
            text(_INSERT_USAGE_EVENT_SQL),
            {
                "user_id": str(user_id),
                "event_type": "usage",
                "tokens": int(tokens),
                "metadata": json.dumps(event_metadata, ensure_ascii=False),
            },
        )
        await session.execute(
            text(_UPSERT_USAGE_DAILY_SQL),
            {
                "user_id": str(user_id),
                "tokens": int(tokens),
                "credits": credits,
                "raw_cost": float(raw_cost_rub),
            },
        )
        if reservation_id:
            await session.execute(text(_COMMIT_RESERVATION_SQL), {"rid": reservation_id})
        return {"from_subscription": from_subscription, "from_topup": from_topup}

    @connection()
    async def refund(
        self,
        *,
        user_id: str,
        credits: int,
        reason: str,
        session: AsyncSession | None = None,
    ) -> None:
        """Компенсировать ранее списанные кредиты (best-effort restitution).

        Используется, когда ``charge()`` уже успешно закоммитился в своей
        транзакции, но что-то ПОСЛЕ него в воркере всё же упало (например,
        не удалось обновить статус job/закоммитить персист хода) — пользователь
        оплатил реальный вызов провайдера, но не увидел ответ. Возвращаем
        кредиты в докуп-кошелёк (не различая, из подписки или докупки было
        исходное списание — упрощение, т.к. для реституции важна только сумма).
        """
        session = require_session(session)
        credits = int(credits)
        if credits <= 0:
            return
        await session.execute(text(_REFUND_TOPUP_SQL), {"user_id": str(user_id), "amt": credits})
        await session.execute(
            text(_INSERT_REFUND_EVENT_SQL),
            {
                "user_id": str(user_id),
                "tokens": 0,
                "metadata": json.dumps({"credits": credits, "reason": reason}, ensure_ascii=False),
            },
        )

    @connection()
    async def apply_webhook(
        self,
        *,
        webhook_id: str,
        event_type: str,
        payload: dict[str, Any] | None,
        user_id: str,
        grant: dict[str, Any],
        period_days: int = 30,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Атомарно применить платёжный вебхук (идемпотентно).

        Если вебхук уже обработан (есть строка billing_webhooks с этим
        webhook_id) — no-op. Иначе в одной транзакции: начисляем грант
        (подписка → продление квоты на ``period_days`` + тариф; докупка → +топап),
        пишем billing_event платежа и фиксируем вебхук как обработанный.
        Атомарность гарантирует отсутствие частичных/двойных начислений:
        при сбое транзакция откатывается, строки вебхука нет → провайдер
        безопасно повторит. ``webhook_id`` для succeeded-платежа = payment_id,
        его же кладём в metadata начисления — по нему возврат находит начисление.
        """
        session = require_session(session)

        exists = (await session.execute(text(_WEBHOOK_EXISTS_SQL), {"wid": webhook_id})).first()
        if exists is not None:
            return {"status": "already_processed"}

        kind = grant.get("kind")
        credits = int(grant.get("credits", 0) or 0)
        amount = float(grant.get("amount_rub", 0) or 0)
        currency = grant.get("currency", "RUB")

        if kind == "subscription":
            # Продлеваем активную платную квоту (докупка времени + лимита), либо
            # создаём новую [today; today+period_days). used не сбрасываем.
            active = (
                await session.execute(text(_ACTIVE_QUOTA_FOR_UPDATE_SQL), {"user_id": str(user_id)})
            ).first()
            if active is not None:
                await session.execute(
                    text(_EXTEND_QUOTA_SQL),
                    {
                        "user_id": str(user_id),
                        "period_start": active[0],
                        "add_limit": credits,
                        "period_days": int(period_days),
                    },
                )
            else:
                await session.execute(
                    text(_INSERT_PAID_QUOTA_SQL),
                    {
                        "user_id": str(user_id),
                        "limit": credits,
                        "period_days": int(period_days),
                    },
                )
            await session.execute(
                text(_SET_PLAN_SQL),
                {
                    "user_id": str(user_id),
                    "plan": grant.get("plan"),
                    "sub_ref": grant.get("provider_ref"),
                },
            )
            event_type_db = "subscription_grant"
        elif kind == "topup":
            await session.execute(text(_ADD_TOPUP_SQL), {"user_id": str(user_id), "amt": credits})
            event_type_db = "topup"
        else:
            return {"status": "ignored"}

        await session.execute(
            text(_INSERT_PAYMENT_EVENT_SQL),
            {
                "user_id": str(user_id),
                "event_type": event_type_db,
                "amount": amount,
                "currency": currency,
                "metadata": json.dumps(
                    {
                        "kind": kind,
                        "plan": grant.get("plan"),
                        "pack_id": grant.get("pack_id"),
                        "credits": credits,
                        "payment_id": webhook_id,
                    },
                    ensure_ascii=False,
                ),
            },
        )
        await session.execute(
            text(_RECORD_WEBHOOK_SQL),
            {
                "wid": webhook_id,
                "etype": event_type,
                "payload": json.dumps(payload or {}, ensure_ascii=False),
                "idem": webhook_id,
            },
        )
        return {"status": "ok", "kind": kind, "credits": credits}

    @connection()
    async def apply_refund(
        self,
        *,
        refund_id: str,
        source_payment_id: str,
        event_type: str,
        payload: dict[str, Any] | None,
        amount_rub: float,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Атомарно откатить кредиты при возврате платежа (идемпотентно).

        Идемпотентность — по ``refund_id`` в той же таблице ``billing_webhooks``
        (id возврата отличается от id платежа, поэтому не конфликтует с исходным
        начислением). Находим начисление по ``payment_id`` в metadata, считаем
        clawback (полный возврат → все кредиты начисления; частичный →
        пропорционально сумме), списываем: докупку с кошелька (не в минус),
        подписку — урезанием лимита активной квоты (но не ниже уже потраченного).
        Всё в одной транзакции: при сбое откат, повтор безопасен.
        """
        session = require_session(session)

        exists = (await session.execute(text(_WEBHOOK_EXISTS_SQL), {"wid": refund_id})).first()
        if exists is not None:
            return {"status": "already_processed"}

        grant_row = (
            await session.execute(text(_FIND_GRANT_BY_PAYMENT_SQL), {"pid": str(source_payment_id)})
        ).first()

        clawback = 0
        status = "no_grant"
        if grant_row is not None:
            user_id, grant_event_type, orig_amount, orig_credits = grant_row
            orig_amount = float(orig_amount or 0)
            orig_credits = int(orig_credits or 0)
            refund_amount = float(amount_rub or 0)
            # Полный возврат (или сумма не определена) → весь грант; иначе пропорция.
            if orig_amount <= 0 or refund_amount >= orig_amount:
                clawback = orig_credits
            else:
                clawback = round(orig_credits * refund_amount / orig_amount)

            if clawback > 0:
                if grant_event_type == "topup":
                    await session.execute(
                        text(_CLAWBACK_TOPUP_SQL),
                        {"user_id": str(user_id), "amt": clawback},
                    )
                else:  # subscription_grant
                    await session.execute(
                        text(_CLAWBACK_QUOTA_SQL),
                        {"user_id": str(user_id), "amt": clawback},
                    )
            await session.execute(
                text(_INSERT_PAYMENT_EVENT_SQL),
                {
                    "user_id": str(user_id),
                    "event_type": "refund",
                    "amount": refund_amount,
                    "currency": "RUB",
                    "metadata": json.dumps(
                        {
                            "kind": "refund",
                            "payment_id": str(source_payment_id),
                            "refund_id": str(refund_id),
                            "credits": -clawback,
                        },
                        ensure_ascii=False,
                    ),
                },
            )
            status = "ok"

        # Вебхук отмечаем обработанным ВСЕГДА (даже если начисления не нашли) —
        # иначе ЮKassa будет ретраить возврат бесконечно.
        await session.execute(
            text(_RECORD_WEBHOOK_SQL),
            {
                "wid": refund_id,
                "etype": event_type,
                "payload": json.dumps(payload or {}, ensure_ascii=False),
                "idem": refund_id,
            },
        )
        return {"status": status, "clawback": clawback}

    @connection()
    async def record_pending_payment(
        self,
        *,
        payment_id: str,
        user_id: str,
        kind: str,
        plan: str | None = None,
        pack_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        """Запомнить инициированный платёж (для сверки, если вебхук не дойдёт)."""
        session = require_session(session)
        await session.execute(
            text(_INSERT_PENDING_PAYMENT_SQL),
            {
                "payment_id": str(payment_id),
                "user_id": str(user_id),
                "kind": kind,
                "plan": plan,
                "pack_id": pack_id,
            },
        )

    @connection()
    async def fetch_stale_pending_payments(
        self,
        *,
        older_than_min: int = 15,
        window_hours: int = 48,
        limit: int = 100,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """Pending-платежи в окне [older_than_min; window_hours] — вебхук мог не дойти."""
        session = require_session(session)
        rows = (
            await session.execute(
                text(_FETCH_STALE_PENDING_SQL),
                {
                    "older_than_min": int(older_than_min),
                    "window_hours": int(window_hours),
                    "lim": int(limit),
                },
            )
        ).fetchall()
        return [
            {
                "payment_id": r[0],
                "user_id": str(r[1]),
                "kind": r[2],
                "plan": r[3],
                "pack_id": r[4],
            }
            for r in rows
        ]

    @connection()
    async def set_payment_status(
        self, *, payment_id: str, status: str, session: AsyncSession | None = None
    ) -> None:
        session = require_session(session)
        await session.execute(
            text(_SET_PAYMENT_STATUS_SQL), {"payment_id": str(payment_id), "status": status}
        )

    @connection()
    async def fetch_usage_daily(
        self, *, user_id: str, since, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        session = require_session(session)
        rows = (
            await session.execute(
                text(_USAGE_DAILY_RANGE_SQL), {"uid": str(user_id), "since": since}
            )
        ).fetchall()
        return [
            {
                "day": row[0],
                "requests": int(row[1] or 0),
                "credits": int(row[2] or 0),
                "tokens": int(row[3] or 0),
            }
            for row in rows
        ]

    @connection()
    async def fetch_usage_events(
        self, *, user_id: str, since, limit: int = 5000, session: AsyncSession | None = None
    ) -> list[dict[str, Any]]:
        session = require_session(session)
        rows = (
            await session.execute(
                text(_USAGE_EVENTS_RANGE_SQL),
                {"uid": str(user_id), "since": since, "lim": int(limit)},
            )
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            raw_meta = row[1]
            if isinstance(raw_meta, dict):
                meta = raw_meta
            elif raw_meta:
                try:
                    meta = json.loads(raw_meta)
                except (ValueError, TypeError):
                    meta = {}
            else:
                meta = {}
            out.append({"tokens": int(row[0] or 0), "metadata": meta})
        return out

    @connection()
    async def list_pricing(self, session: AsyncSession | None = None) -> list[dict[str, Any]]:
        session = require_session(session)
        rows = (await session.execute(text(_LIST_PRICING_SQL))).fetchall()
        return [
            {
                "provider": row[0] or None,
                "model_id": row[1],
                "price_in_rub_per_1k": float(row[2]) if row[2] is not None else None,
                "price_out_rub_per_1k": float(row[3]) if row[3] is not None else None,
                "margin_override": float(row[4]) if row[4] is not None else None,
                "model_class": row[5],
                "updated_by": row[6],
                "updated_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
            }
            for row in rows
        ]

    @connection()
    async def upsert_model_pricing(
        self,
        *,
        provider: str = "",
        model_id: str,
        price_in: float,
        price_out: float,
        margin_override: float | None = None,
        model_class: str | None = None,
        updated_by: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        session = require_session(session)
        await session.execute(
            text(_UPSERT_PRICING_SQL),
            {
                "provider": (provider or "").strip().lower(),
                "model_id": model_id,
                "price_in": float(price_in),
                "price_out": float(price_out),
                "margin_override": float(margin_override) if margin_override is not None else None,
                "model_class": model_class,
                "updated_by": updated_by,
            },
        )

    @connection()
    async def delete_model_pricing(
        self, *, model_id: str, provider: str = "", session: AsyncSession | None = None
    ) -> bool:
        session = require_session(session)
        result = await session.execute(
            text(
                "DELETE FROM profile.model_pricing "
                "WHERE provider = :provider AND model_id = :model_id"
            ),
            {"provider": (provider or "").strip().lower(), "model_id": model_id},
        )
        return (result.rowcount or 0) > 0
