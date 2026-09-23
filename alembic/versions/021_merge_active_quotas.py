"""Слияние перекрывающихся активных квот в одну строку на пользователя (аудит T1.2).

Инвариант: у пользователя одна активная квота. Он нарушался после перехода через 1-е
число у платника: `_PROVISION_QUOTA_SQL` вставлял календарную free-строку РЯДОМ с
продлённой платной (оплата продлевает строку, а не плодит). Остаток читался по ОДНОЙ
строке (newest), а списание било по ВСЕМ — платник и жёг бесплатный пакет даром
(`GREATEST(0, 0 - credits) = 0`), и терял доступ к оплаченному балансу второй строки.

Код уже не создаёт новые overlap'ы (provision под `WHERE NOT EXISTS активная`) и списывает
только читанную строку. Эта миграция чинит УЖЕ существующие overlap'ы: сливает
перекрывающиеся активные строки одного пользователя в одну — период [MIN start; MAX end),
лимит и used суммируются (сохраняя суммарный баланс и самый широкий период).

Данные-CTE `active` вычисляется ОДИН раз (снапшот), поэтому DELETE лишних и UPDATE
оставленной строки согласованы. Downgrade не может «расслить» — no-op.

Revision ID: 021_merge_active_quotas
Revises: 020_notifications
"""

from alembic import op

revision = "021_merge_active_quotas"
down_revision = "020_notifications"
branch_labels = None
depends_on = None


_MERGE_SQL = """
WITH active AS (
    SELECT user_id,
           MIN(period_start) AS ps,
           MAX(period_end)   AS pe,
           SUM("limit")      AS lim,
           SUM(used)         AS usd,
           MIN(id)           AS keep_id
    FROM profile.token_quotas
    WHERE period_start <= CURRENT_DATE AND period_end > CURRENT_DATE
    GROUP BY user_id
    HAVING COUNT(*) > 1
),
del AS (
    DELETE FROM profile.token_quotas q
    USING active a
    WHERE q.user_id = a.user_id
      AND q.period_start <= CURRENT_DATE AND q.period_end > CURRENT_DATE
      AND q.id <> a.keep_id
    RETURNING 1
)
UPDATE profile.token_quotas q
SET period_start = a.ps,
    period_end   = a.pe,
    "limit"      = a.lim,
    used         = a.usd,
    updated_at   = now()
FROM active a
WHERE q.id = a.keep_id;
"""


def upgrade() -> None:
    op.execute(_MERGE_SQL)


def downgrade() -> None:
    # Слияние необратимо (исходные строки уже удалены) — откат ничего не делает.
    pass
