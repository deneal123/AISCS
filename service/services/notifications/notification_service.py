"""Жизненные уведомления: подписка, кредиты, платежи, реактивация.

Три правила, которые здесь не обсуждаются:

1. **Отписка гасит ВСЁ.** Явно отписавшийся человек не получает ничего, включая сервисные
   письма. Формально закон разрешает слать ему уведомления о состоянии аккаунта — но
   человек уже сказал «не пиши мне», и обходить это через юридическую лазейку значит
   получить жалобу на спам вместо пользователя.

2. **Реклама только по отдельному согласию.** `consent_pd_at` (обработка ПД) — это НЕ
   согласие на рекламу: ФЗ «О рекламе», ст. 18 требует отдельного. Реактивационное письмо
   («давно не заходили») — реклама, и оно уходит только при `marketing_consent_at`.

3. **Идемпотентность.** Beat крутится по расписанию; без dedup_key одно и то же письмо
   уходило бы каждый прогон. Ключ — сам факт события: дата конца периода, id платежа,
   месяц простоя.

Плюс частотный лимит: даже когда сработали три триггера сразу, человек не должен получить
три письма за день.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

logger = logging.getLogger(__name__)

SERVICE_KINDS = frozenset({"subscription_expiring", "low_credits", "payment_failed"})
MARKETING_KINDS = frozenset({"reactivation"})


def unsubscribe_token(user_id: str, secret: str) -> str:
    """Подпись отписки. Stateless: токен не хранится, а проверяется пересчётом.

    Без подписи ссылка вида `?u=<uuid>` позволила бы отписать ЛЮБОГО, просто подставив
    чужой id.
    """
    return hmac.new(secret.encode(), f"unsub:{user_id}".encode(), hashlib.sha256).hexdigest()[:32]


def verify_unsubscribe_token(user_id: str, token: str, secret: str) -> bool:
    # Сравниваем БАЙТЫ, а не строки: compare_digest кидает TypeError, если str содержит
    # не-ASCII. Голая строка роняла публичный эндпоинт отписки в 500 вместо честного 403
    # — достаточно было кириллицы в подписи, хоть из кривого почтового клиента, хоть от
    # того, кто ткнул наугад.
    expected = unsubscribe_token(user_id, secret).encode()
    return hmac.compare_digest(expected, str(token or "").encode())


class NotificationService:
    def __init__(self, pg_connector, mailer, config):
        self.pg = pg_connector
        self.mailer = mailer
        self.config = config

    # Сама отписка живёт в ProfileService.unsubscribe_all: она обязана инвалидировать
    # кэш профиля и снимать согласие на рекламу, а сырой UPDATE отсюда не делал ни того,
    # ни другого.

    # ----------------------------------------------------------------- рассылка --
    async def run(self) -> dict[str, int]:
        """Один прогон по всем триггерам. → сколько писем ушло по каждому виду."""
        cfg = self.config.notifications
        if not cfg.enabled:
            return {}

        sent: dict[str, int] = {}
        # Сколько писем ушло КАЖДОМУ пользователю в ЭТОМ прогоне. Полагаться только на
        # счётчик из БД нельзя: у пользователя могут сработать три триггера подряд, и
        # запись предыдущего письма не обязана быть видна следующей проверке в пределах
        # одного прогона (разные сессии). Без этого счётчика частотный лимит пропускал
        # пачку писем разом — ровно то, от чего он должен защищать.
        sent_now: dict[str, int] = {}
        for kind, rows in (
            ("subscription_expiring", await self._expiring_subscriptions()),
            ("low_credits", await self._low_credits()),
            ("payment_failed", await self._failed_payments()),
            ("reactivation", await self._idle_users()),
        ):
            for row in rows:
                if await self._send(kind, row, sent_now=sent_now):
                    sent[kind] = sent.get(kind, 0) + 1
        if sent:
            logger.info("уведомления отправлены: %s", sent)
        return sent

    async def _send(self, kind: str, row: dict, *, sent_now: dict[str, int] | None = None) -> bool:
        from service.infrastructure.mail import lifecycle_templates as tpl

        user_id = str(row["user_id"])
        if not await self._may_send(user_id, kind, row["dedup_key"], sent_now=sent_now):
            return False

        app_url = str(self.config.notifications.app_url).rstrip("/")
        token = unsubscribe_token(user_id, self.config.auth.secret)
        unsub = f"{app_url}/api/notifications/unsubscribe?u={user_id}&t={token}"

        builders = {
            "subscription_expiring": lambda: tpl.subscription_expiring(
                days_left=row["days_left"], plan=row["plan"], app_url=app_url, unsubscribe_url=unsub
            ),
            "low_credits": lambda: tpl.low_credits(
                remaining=row["remaining"], app_url=app_url, unsubscribe_url=unsub
            ),
            "payment_failed": lambda: tpl.payment_failed(
                amount_rub=row["amount_rub"], app_url=app_url, unsubscribe_url=unsub
            ),
            "reactivation": lambda: tpl.reactivation(
                credits=row["credits"],
                days_idle=row["days_idle"],
                app_url=app_url,
                unsubscribe_url=unsub,
            ),
        }
        subject, html, plain = builders[kind]()

        try:
            await self.mailer.send(to=row["email"], subject=subject, html=html, text=plain)
        except Exception:
            logger.warning("письмо %s для %s не ушло", kind, user_id, exc_info=True)
            return False

        # Пишем в журнал ТОЛЬКО после успешной отправки: иначе сбой SMTP навсегда
        # заблокировал бы повтор (dedup_key уже занят), и человек не получил бы письмо
        # вообще.
        await self._log(user_id, kind, row["dedup_key"])
        if sent_now is not None:
            sent_now[user_id] = sent_now.get(user_id, 0) + 1
        return True

    async def _may_send(
        self, user_id: str, kind: str, dedup_key: str, *, sent_now: dict[str, int] | None = None
    ) -> bool:
        cfg = self.config.notifications
        # Уже написали ему в этом прогоне — дальше не считаем: лимит исчерпан.
        if (sent_now or {}).get(user_id, 0) >= int(cfg.max_per_window):
            return False
        async with self.pg.get_session_context() as s:
            already = await s.execute(
                text(
                    "SELECT 1 FROM profile.notification_log "
                    "WHERE user_id = :uid AND kind = :k AND dedup_key = :d LIMIT 1"
                ),
                {"uid": user_id, "k": kind, "d": dedup_key},
            )
            if already.first():
                return False

            # Частотный лимит: три сработавших триггера не должны дать три письма за день.
            recent = await s.execute(
                text(
                    "SELECT COUNT(*) FROM profile.notification_log "
                    "WHERE user_id = :uid AND sent_at > NOW() - (:w * INTERVAL '1 day')"
                ),
                {"uid": user_id, "w": int(cfg.frequency_window_days)},
            )
            count = int(recent.scalar() or 0)
            if count >= int(cfg.max_per_window):
                logger.debug("частотный лимит: %s уже получил %s писем", user_id, count)
                return False
        return True

    async def _log(self, user_id: str, kind: str, dedup_key: str) -> None:
        async with self.pg.get_session_context() as s:
            await s.execute(
                text(
                    "INSERT INTO profile.notification_log (user_id, kind, dedup_key) "
                    "VALUES (:uid, :k, :d) ON CONFLICT DO NOTHING"
                ),
                {"uid": user_id, "k": kind, "d": dedup_key},
            )
            await s.commit()

    # ------------------------------------------------------------- триггеры --
    # `unsubscribed_at IS NULL` — в КАЖДОМ запросе, а не в общем фильтре: забыть его в
    # одном месте значит написать отписавшемуся человеку.

    async def _expiring_subscriptions(self) -> list[dict]:
        days = int(self.config.notifications.subscription_notice_days)
        async with self.pg.get_session_context() as s:
            res = await s.execute(
                text(
                    """
                    SELECT u.id, u.email, u.plan, q.period_end
                    FROM profile.token_quotas q
                    JOIN profile."user" u ON u.id = q.user_id
                    WHERE u.plan <> 'free'
                      AND u.email_verified = true
                      AND u.unsubscribed_at IS NULL
                      AND q.period_end = CURRENT_DATE + CAST(:d AS INTEGER)
                    """
                ),
                {"d": days},
            )
            return [
                {
                    "user_id": r[0],
                    "email": r[1],
                    "plan": r[2],
                    "days_left": days,
                    "dedup_key": str(r[3]),  # дата конца периода: одно письмо на период
                }
                for r in res.fetchall()
            ]

    async def _low_credits(self) -> list[dict]:
        threshold = float(self.config.notifications.low_credits_threshold)
        async with self.pg.get_session_context() as s:
            res = await s.execute(
                text(
                    """
                    SELECT u.id, u.email, q.limit - q.used + u.topup_credit_balance AS remaining,
                           q.period_start
                    FROM profile.token_quotas q
                    JOIN profile."user" u ON u.id = q.user_id
                    WHERE u.email_verified = true
                      AND u.unsubscribed_at IS NULL
                      AND q.period_end >= CURRENT_DATE
                      AND q.limit > 0
                      AND (q.limit - q.used + u.topup_credit_balance) > 0
                      AND (q.limit - q.used + u.topup_credit_balance)::float / q.limit < :t
                    """
                ),
                {"t": threshold},
            )
            return [
                {
                    "user_id": r[0],
                    "email": r[1],
                    "remaining": int(r[2]),
                    "dedup_key": str(r[3]),  # один раз за период, а не каждый день
                }
                for r in res.fetchall()
            ]

    async def _failed_payments(self) -> list[dict]:
        """Отклонённые платежи за последние двое суток.

        Суммы в `billing_payments` НЕТ — там только план или пак. Поэтому берём её из
        прайса конфига, а если не нашли (пак переименовали, план убрали) — письмо уходит
        БЕЗ суммы. Выдумывать сумму в письме о деньгах нельзя.
        """
        async with self.pg.get_session_context() as s:
            res = await s.execute(
                text(
                    """
                    SELECT u.id, u.email, p.plan, p.pack_id, p.payment_id
                    FROM profile.billing_payments p
                    JOIN profile."user" u ON u.id = p.user_id
                    WHERE p.status IN ('canceled', 'failed')
                      AND u.email_verified = true
                      AND u.unsubscribed_at IS NULL
                      AND p.updated_at > NOW() - INTERVAL '2 days'
                    """
                )
            )
            return [
                {
                    "user_id": r[0],
                    "email": r[1],
                    "amount_rub": self._payment_amount(plan=r[2], pack_id=r[3]),
                    "dedup_key": str(r[4]),  # id платежа: одно письмо на попытку
                }
                for r in res.fetchall()
            ]

    def _payment_amount(self, *, plan: str | None, pack_id: str | None) -> float | None:
        billing = self.config.billing
        if plan:
            price = (billing.plan_prices_rub or {}).get(plan)
            if price:
                return float(price)
        if pack_id:
            for pack in billing.topup_packs or []:
                if isinstance(pack, dict) and pack.get("id") == pack_id:
                    return float(pack.get("price_rub") or 0) or None
        return None

    async def _idle_users(self) -> list[dict]:
        """Реактивация — единственное МАРКЕТИНГОВОЕ письмо.

        `marketing_consent_at IS NOT NULL` — обязательное условие, а не фильтр «на всякий
        случай»: согласие на обработку ПД рекламу не покрывает.

        Простой считаем по последнему сообщению в чате: отдельная колонка last_active_at
        означала бы запись в БД на каждое действие пользователя ради одного письма в месяц.
        """
        days = int(self.config.notifications.idle_days)
        async with self.pg.get_session_context() as s:
            res = await s.execute(
                text(
                    """
                    SELECT u.id, u.email,
                           COALESCE(q.limit - q.used, 0) + u.topup_credit_balance AS credits
                    FROM profile."user" u
                    LEFT JOIN profile.token_quotas q
                           ON q.user_id = u.id AND q.period_end >= CURRENT_DATE
                    WHERE u.email_verified = true
                      AND u.unsubscribed_at IS NULL
                      AND u.marketing_consent_at IS NOT NULL
                      AND COALESCE(q.limit - q.used, 0) + u.topup_credit_balance > 0
                      AND NOT EXISTS (
                          SELECT 1 FROM profile.chat_messages m
                          JOIN profile.chat_threads t ON t.id = m.thread_id
                          WHERE t.user_id = u.id
                            AND m.created_at > NOW() - (:w * INTERVAL '1 day')
                      )
                    """
                ),
                {"w": days},
            )
            month = date.today().strftime("%Y-%m")
            return [
                {
                    "user_id": r[0],
                    "email": r[1],
                    "credits": int(r[2]),
                    "days_idle": days,
                    "dedup_key": month,  # не чаще раза в месяц
                }
                for r in res.fetchall()
            ]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _days_ago(days: int) -> datetime:
    return _utcnow() - timedelta(days=days)
