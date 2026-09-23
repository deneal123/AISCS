"""SQL биллинга: все запросы в одном месте, отдельно от логики.

🔴 У ЗАПРОСОВ СВОЯ ПРИЧИНА МЕНЯТЬСЯ — схема БД, — а у репозитория своя: правила денег.
Пока они лежали вперемешку, файл разросся до 1137 строк при потолке 750, и каждая правка
арифметики тащила за собой перечитывание двух сотен строк SQL.

⚠️ ИМЕНА ОСТАВЛЕНЫ КАК БЫЛИ (с ведущим подчёркиванием): это перенос, а не переименование.
Смешивать перенос с переименованием в одном коммите значит терять читаемость диффа.
"""

from __future__ import annotations

_INSERT_USAGE_EVENT_SQL = (
    "INSERT INTO profile.billing_events (user_id, event_type, tokens, metadata) "
    "VALUES (CAST(:user_id AS uuid), :event_type, :tokens, CAST(:metadata AS jsonb))"
)
# Идемпотентность списания по ``job_id``: `task_acks_late` редоставляет задачу, если
# воркер умер ПОСЛЕ коммита списания, но до ack — без гейта запрос оплачивался бы дважды.
# Проверка идёт под той же ``FOR UPDATE`` на строке квоты, что сериализует конкурентные
# ``charge()`` одного юзера, поэтому check-then-insert безопасен без уникального индекса.
_USAGE_EVENT_EXISTS_SQL = (
    "SELECT 1 FROM profile.billing_events "
    "WHERE user_id = CAST(:user_id AS uuid) AND event_type = 'usage' "
    "AND metadata->>'idempotency_key' = :idem_key LIMIT 1"
)
# Апсерт суточного агрегата: первая запись дня создаётся, последующие
# накапливаются. CURRENT_DATE берём в БД, чтобы не зависеть от часового пояса воркера.
_UPSERT_USAGE_DAILY_SQL = (
    "INSERT INTO profile.usage_daily (user_id, day, requests, tokens, credits, raw_cost_rub) "
    "VALUES (CAST(:user_id AS uuid), CURRENT_DATE, 1, :tokens, :credits, :raw_cost) "
    "ON CONFLICT (user_id, day) DO UPDATE SET "
    "requests = profile.usage_daily.requests + 1, "
    "tokens = profile.usage_daily.tokens + EXCLUDED.tokens, "
    "credits = profile.usage_daily.credits + EXCLUDED.credits, "
    "raw_cost_rub = profile.usage_daily.raw_cost_rub + EXCLUDED.raw_cost_rub, "
    "updated_at = now()"
)
# Баланс: тариф/докуп-кошелёк пользователя + активная квота периода (LEFT JOIN —
# строки квоты может не быть у новых free-юзеров). "limit" — зарезервированное
# слово, экранируем.
_BALANCE_SQL = (
    'SELECT u.plan, u.topup_credit_balance, q."limit", q.used, q.period_end '
    "FROM profile.user u "
    "LEFT JOIN profile.token_quotas q "
    "ON q.user_id = u.id AND q.period_start <= CURRENT_DATE AND q.period_end > CURRENT_DATE "
    "WHERE u.id = CAST(:user_id AS uuid) "
    "ORDER BY q.period_start DESC LIMIT 1"
)
_USER_EMAIL_SQL = "SELECT email FROM profile.user WHERE id = CAST(:user_id AS uuid)"
# Провижининг free-квоты: идемпотентно по (user_id, period_start) И только при отсутствии
# активной квоты. 🔴 Инвариант — ОДНА активная квота на пользователя: остаток читается по
# одной строке (_ACTIVE_REMAINING_SQL), а списание бьёт по всем, так что вторая (free
# рядом с продлённой платной) жгла бы пакет даром и прятала оплаченный баланс.
_PROVISION_QUOTA_SQL = (
    'INSERT INTO profile.token_quotas (user_id, period_start, period_end, "limit", used) '
    "SELECT CAST(:user_id AS uuid), :period_start, :period_end, :limit, 0 "
    "WHERE NOT EXISTS (SELECT 1 FROM profile.token_quotas "
    "WHERE user_id = CAST(:user_id AS uuid) "
    "AND period_start <= CURRENT_DATE AND period_end > CURRENT_DATE) "
    "ON CONFLICT (user_id, period_start) DO NOTHING"
)
_ACTIVE_REMAINING_SQL = (
    'SELECT ("limit" - used) FROM profile.token_quotas '
    "WHERE user_id = CAST(:user_id AS uuid) AND period_start <= CURRENT_DATE "
    "AND period_end > CURRENT_DATE ORDER BY period_start DESC LIMIT 1 FOR UPDATE"
)
# Списание бьёт ТОЛЬКО по строке, чей остаток читал _ACTIVE_REMAINING_SQL (newest
# активная, уже под FOR UPDATE). Раньше UPDATE без LIMIT списывал со ВСЕХ активных строк,
# а читали одну — при legacy-overlap'е платная квота драйнилась «в тёмную». Теперь чтение
# и списание согласованы на одной и той же строке.
_DEDUCT_SUBSCRIPTION_SQL = (
    "UPDATE profile.token_quotas SET used = used + :amt, updated_at = now() "
    "WHERE id = (SELECT id FROM profile.token_quotas "
    "WHERE user_id = CAST(:user_id AS uuid) "
    "AND period_start <= CURRENT_DATE AND period_end > CURRENT_DATE "
    "ORDER BY period_start DESC LIMIT 1)"
)
# Остаток докупа ПОД БЛОКИРОВКОЙ: `GREATEST(0,…)` ниже обрезает молча, и расхождение
# «хотели/сняли» уезжало в события и в реституцию (та возвращает номинал). Замер: снято 100
# при номинале 500, возврат 500 → +400 кредитов из воздуха. См. `domain/charge_math.py`.
_TOPUP_BALANCE_FOR_UPDATE_SQL = (
    'SELECT topup_credit_balance FROM profile."user" WHERE id = CAST(:user_id AS uuid) FOR UPDATE'
)
_DEDUCT_TOPUP_SQL = (
    "UPDATE profile.user "
    "SET topup_credit_balance = GREATEST(0, topup_credit_balance - :amt) "
    "WHERE id = CAST(:user_id AS uuid)"
)
# --- резервирование (анти-TOCTOU precheck) --------------------------------- #
_TOPUP_BALANCE_SQL = (
    "SELECT topup_credit_balance FROM profile.user WHERE id = CAST(:user_id AS uuid)"
)
_SUM_ACTIVE_RESERVATIONS_SQL = (
    "SELECT COALESCE(SUM(tokens_reserved), 0) FROM profile.token_reservations "
    "WHERE user_id = CAST(:user_id AS uuid) AND status = 'reserved' AND expires_at > now()"
)
_INSERT_RESERVATION_SQL = (
    "INSERT INTO profile.token_reservations "
    "(reservation_id, user_id, tokens_reserved, expires_at, status) "
    "VALUES (CAST(:rid AS uuid), CAST(:user_id AS uuid), :amount, :expires_at, 'reserved')"
)
_COMMIT_RESERVATION_SQL = (
    "UPDATE profile.token_reservations SET status = 'committed', committed_at = now() "
    "WHERE reservation_id = CAST(:rid AS uuid) AND status = 'reserved'"
)
_RELEASE_RESERVATION_SQL = (
    "UPDATE profile.token_reservations SET status = 'refunded', refunded_at = now() "
    "WHERE reservation_id = CAST(:rid AS uuid) AND status = 'reserved'"
)
_CLEANUP_EXPIRED_RESERVATIONS_SQL = (
    "UPDATE profile.token_reservations SET status = 'refunded', refunded_at = now() "
    "WHERE status = 'reserved' AND expires_at <= now() RETURNING reservation_id"
)
_RESERVATION_SNAPSHOT_SQL = (
    "SELECT COUNT(*) FILTER (WHERE status = 'reserved' AND expires_at > now()), "
    "COUNT(*) FILTER (WHERE status = 'reserved' AND expires_at <= now()) "
    "FROM profile.token_reservations"
)
_COST_GUARD_EVENTS_SQL = (
    "SELECT COUNT(*) FILTER (WHERE event_type = 'usage' AND metadata ? 'billing_fallback'), "
    "COUNT(*) FILTER (WHERE event_type = 'usage' "
    "AND metadata ->> 'stop_reason' = 'prompt_budget_reached'), "
    "COALESCE(SUM(CASE WHEN event_type = 'usage' AND metadata ? 'raw_cost_rub' "
    "AND metadata ->> 'raw_cost_rub' ~ '^-?(\\d+(\\.\\d*)?|\\.\\d+)([eE][+-]?\\d+)?$' "
    "THEN (metadata ->> 'raw_cost_rub')::numeric ELSE 0 END), 0) "
    "FROM profile.billing_events WHERE created_at >= :since"
)
_REFUND_TOPUP_SQL = (
    "UPDATE profile.user SET topup_credit_balance = topup_credit_balance + :amt "
    "WHERE id = CAST(:user_id AS uuid)"
)
_INSERT_REFUND_EVENT_SQL = (
    "INSERT INTO profile.billing_events (user_id, event_type, tokens, metadata) "
    "VALUES (CAST(:user_id AS uuid), 'refund', :tokens, CAST(:metadata AS jsonb))"
)
# --- платежи (Фаза 4) ----------------------------------------------------- #
_WEBHOOK_EXISTS_SQL = "SELECT 1 FROM profile.billing_webhooks WHERE webhook_id = :wid LIMIT 1"
_RECORD_WEBHOOK_SQL = (
    "INSERT INTO profile.billing_webhooks "
    "(webhook_id, event_type, payload, idempotency_key, processed_at) "
    "VALUES (:wid, :etype, CAST(:payload AS jsonb), :idem, now())"
)
# Подписка = скользящие N дней от даты оплаты, НЕ календарный месяц: купленная 25-го не
# должна сгорать 1-го. Повторная оплата ПРОДЛЕВАЕТ срок и ДОБАВЛЯЕТ лимит — перезапись
# забирала бы деньги, не давая кредитов. Под блокировкой строки: сериализует конкурентные
# подписочные вебхуки одного юзера.
_ACTIVE_QUOTA_FOR_UPDATE_SQL = (
    'SELECT period_start, period_end, "limit" FROM profile.token_quotas '
    "WHERE user_id = CAST(:user_id AS uuid) AND period_end > CURRENT_DATE "
    "ORDER BY period_start DESC LIMIT 1 FOR UPDATE"
)
# Продление активной квоты: +лимит, конец сдвигается на period_days от ТЕКУЩЕГО
# конца (докупка времени встык). used не трогаем — тот же кошелёк.
_EXTEND_QUOTA_SQL = (
    'UPDATE profile.token_quotas SET "limit" = "limit" + :add_limit, '
    "period_end = period_end + make_interval(days => :period_days), updated_at = now() "
    "WHERE user_id = CAST(:user_id AS uuid) AND period_start = :period_start"
)
# Новая квота: [today; today + period_days).
_INSERT_PAID_QUOTA_SQL = (
    'INSERT INTO profile.token_quotas (user_id, period_start, period_end, "limit", used) '
    "VALUES (CAST(:user_id AS uuid), CURRENT_DATE, "
    "CURRENT_DATE + make_interval(days => :period_days), :limit, 0) "
    "ON CONFLICT (user_id, period_start) "
    'DO UPDATE SET "limit" = profile.token_quotas."limit" + EXCLUDED."limit", '
    "period_end = GREATEST(profile.token_quotas.period_end, EXCLUDED.period_end), "
    "updated_at = now()"
)
_SET_PLAN_SQL = (
    "UPDATE profile.user SET plan = :plan, payment_subscription_id = :sub_ref "
    "WHERE id = CAST(:user_id AS uuid)"
)
_ADD_TOPUP_SQL = (
    "UPDATE profile.user SET topup_credit_balance = topup_credit_balance + :amt "
    "WHERE id = CAST(:user_id AS uuid)"
)
_INSERT_PAYMENT_EVENT_SQL = (
    "INSERT INTO profile.billing_events (user_id, event_type, amount, currency, metadata) "
    "VALUES (CAST(:user_id AS uuid), :event_type, :amount, :currency, CAST(:metadata AS jsonb))"
)
# --- возврат платежа (clawback) ------------------------------------------- #
# Исходное начисление ищем по payment_id, который apply_webhook кладёт в metadata.
_FIND_GRANT_BY_PAYMENT_SQL = (
    "SELECT user_id, event_type, amount, COALESCE((metadata->>'credits')::bigint, 0) "
    "FROM profile.billing_events "
    "WHERE metadata->>'payment_id' = :pid AND event_type IN ('topup', 'subscription_grant') "
    "ORDER BY created_at LIMIT 1"
)
# Списываем докупленные кредиты, но не в минус.
_CLAWBACK_TOPUP_SQL = (
    "UPDATE profile.user "
    "SET topup_credit_balance = GREATEST(0, topup_credit_balance - :amt) "
    "WHERE id = CAST(:user_id AS uuid)"
)
# Урезаем лимит активной подписочной квоты, но НЕ ниже уже потраченного (used):
# возврат не может «отобрать» кредиты, которые пользователь уже израсходовал.
_CLAWBACK_QUOTA_SQL = (
    'UPDATE profile.token_quotas SET "limit" = GREATEST(used, "limit" - :amt), updated_at = now() '
    "WHERE user_id = CAST(:user_id AS uuid) AND period_end > CURRENT_DATE"
)
# --- сверка платежей (reconciliation) ------------------------------------- #
# Сохраняем инициированный платёж; повторный checkout с тем же id — no-op.
_INSERT_PENDING_PAYMENT_SQL = (
    "INSERT INTO profile.billing_payments (payment_id, user_id, kind, plan, pack_id, status) "
    "VALUES (:payment_id, CAST(:user_id AS uuid), :kind, :plan, :pack_id, 'pending') "
    "ON CONFLICT (payment_id) DO NOTHING"
)
# «Зависшие» pending в окне [older_than_min; window_hours] — вебхук мог не дойти,
# но платёж ещё в разумном возрасте. Свежие (< older_than_min) не трогаем —
# вебхук в пути; слишком старые (> window_hours) выпадают из сверки (24ч ретраев
# ЮKassa прошли — дальше ручной разбор), чтобы не дёргать их вечно.
_FETCH_STALE_PENDING_SQL = (
    "SELECT payment_id, user_id, kind, plan, pack_id FROM profile.billing_payments "
    "WHERE status = 'pending' "
    "AND created_at < now() - make_interval(mins => :older_than_min) "
    "AND created_at > now() - make_interval(hours => :window_hours) "
    "ORDER BY created_at LIMIT :lim"
)
_SET_PAYMENT_STATUS_SQL = (
    "UPDATE profile.billing_payments SET status = :status, updated_at = now() "
    "WHERE payment_id = :payment_id"
)
# --- аналитика (Фаза 6) --------------------------------------------------- #
_USAGE_DAILY_RANGE_SQL = (
    "SELECT day, requests, credits, tokens FROM profile.usage_daily "
    "WHERE user_id = CAST(:uid AS uuid) AND day >= :since ORDER BY day"
)
_USAGE_EVENTS_RANGE_SQL = (
    "SELECT tokens, metadata FROM profile.billing_events "
    "WHERE user_id = CAST(:uid AS uuid) AND event_type = 'usage' AND created_at >= :since "
    "ORDER BY created_at DESC LIMIT :lim"
)
_RECENT_EVENTS_SQL = (
    "SELECT event_type, tokens, amount, currency, metadata, created_at "
    "FROM profile.billing_events WHERE user_id = CAST(:uid AS uuid) "
    "ORDER BY created_at DESC LIMIT :lim"
)
_INSERT_FLAG_EVENT_SQL = (
    "INSERT INTO profile.billing_events (user_id, event_type, metadata) "
    "VALUES (CAST(:user_id AS uuid), :event_type, CAST(:metadata AS jsonb))"
)
# --- админ (Фаза 7): управление ценами + сверка маржи --------------------- #
_LIST_PRICING_SQL = (
    "SELECT provider, model_id, price_in_rub_per_1k, price_out_rub_per_1k, margin_override, "
    "model_class, updated_by, updated_at FROM profile.model_pricing ORDER BY provider, model_id"
)
_USAGE_TOTALS_SQL = (
    "SELECT COALESCE(SUM(credits), 0), COALESCE(SUM(raw_cost_rub), 0), "
    "COALESCE(SUM(requests), 0) FROM profile.usage_daily WHERE day >= :since"
)
_UPSERT_PRICING_SQL = (
    "INSERT INTO profile.model_pricing (provider, model_id, price_in_rub_per_1k, "
    "price_out_rub_per_1k, margin_override, model_class, updated_by) "
    "VALUES (:provider, :model_id, :price_in, :price_out, :margin_override, "
    ":model_class, :updated_by) "
    "ON CONFLICT (provider, model_id) DO UPDATE SET "
    "price_in_rub_per_1k = EXCLUDED.price_in_rub_per_1k, "
    "price_out_rub_per_1k = EXCLUDED.price_out_rub_per_1k, "
    "margin_override = EXCLUDED.margin_override, "
    "model_class = EXCLUDED.model_class, "
    "updated_by = EXCLUDED.updated_by, updated_at = now()"
)
_DELETE_SYNCED_PRICING_SQL = (
    "DELETE FROM profile.model_pricing WHERE provider = :provider "
    "AND (updated_by = 'routerai-seed' OR updated_by LIKE :source_prefix)"
)
_UPSERT_SYNCED_PRICING_SQL = (
    "INSERT INTO profile.model_pricing (provider, model_id, price_in_rub_per_1k, "
    "price_out_rub_per_1k, updated_by) "
    "VALUES (:provider, :model_id, :price_in, :price_out, :updated_by) "
    "ON CONFLICT (provider, model_id) DO UPDATE SET "
    "price_in_rub_per_1k = EXCLUDED.price_in_rub_per_1k, "
    "price_out_rub_per_1k = EXCLUDED.price_out_rub_per_1k, "
    "updated_by = EXCLUDED.updated_by, updated_at = now() "
    "WHERE profile.model_pricing.updated_by IS NULL "
    "OR profile.model_pricing.updated_by = 'routerai-seed' "
    "OR profile.model_pricing.updated_by LIKE :source_prefix"
)
