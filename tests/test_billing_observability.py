"""Списание оставляет в истории то, чем его потом расследуют.

🔴 ЗАМЕР ПО ЖИВОЙ БАЗЕ (579 списаний dev): у 3 событий цена оказалась выше снятого — суммарно
1200 кредитов не покрыл никто, а самое дорогое списание было 22 751. И восстановить по
истории, СКОЛЬКО именно не покрыто и НАСКОЛЬКО оценка разошлась с ценой, было нечем:

* поля `uncovered` не существовало — разницу приходилось считать вручную по двум другим;
* поля `reserved_estimate` не было НИ У ОДНОГО из 579 событий, то есть связь «резерв → факт»
  терялась целиком.

Логи для этого не годятся: они ротируются, а событие живёт. Именно по этим двум числам
настраивается множитель резерва и ловится переспенд.

⚠️ Оба поля пишутся ТОЛЬКО когда есть что писать: поле-ноль у 99.5% событий не добавляет
ничего, а искать по нему становится труднее.
"""

from __future__ import annotations

import json

import pytest


class _Session:
    """Двойник сессии: отвечает по характерному фрагменту SQL и копит вставленные события."""

    def __init__(self, *, quota_remaining: int, topup: int):
        self.quota_remaining = quota_remaining
        self.topup = topup
        self.events: list[dict] = []

    async def execute(self, statement, params=None):
        sql, params = str(statement), params or {}

        class _R:
            def __init__(self, row=None):
                self._row = row

            def first(self):
                return self._row

            def scalar(self):
                return self._row[0] if self._row else None

        if 'limit" - used' in sql:
            return _R((self.quota_remaining,))
        if "topup_credit_balance FROM profile" in sql and "FOR UPDATE" in sql:
            return _R((self.topup,))
        if "INSERT INTO profile.billing_events" in sql:
            self.events.append(dict(params))
        return _R()

    async def commit(self):
        return None

    def usage_metadata(self) -> dict:
        """Метаданные последнего usage-события — то, что реально уедет в базу."""
        usage = [e for e in self.events if e.get("event_type") == "usage"]
        assert usage, "usage-событие не записано вовсе"
        return json.loads(usage[-1]["metadata"])


async def _charge(session, credits: int, metadata: dict | None = None):
    from datetime import date, timedelta

    from service.services.billing.persistence.billing_repository import BillingRepository

    return await BillingRepository(None).charge(
        user_id="11111111-1111-1111-1111-111111111111",
        credits=credits,
        tokens=100,
        raw_cost_rub=1.0,
        free_plan_credits=0,
        period_start=date.today(),
        period_end=date.today() + timedelta(days=30),
        metadata=metadata,
        session=session,
    )


# --- недобор виден в истории -------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_an_uncovered_charge_leaves_a_trace():
    """🔴 ГЛАВНОЕ. Цена 500, баланса на 100 — в событии обязано быть видно, что 400 не покрыто."""
    session = _Session(quota_remaining=0, topup=100)

    await _charge(session, 500)

    meta = session.usage_metadata()
    assert meta.get("uncovered") == 400, (
        "размер недобора не сохранён — по истории не узнать, сколько заплатила платформа"
    )
    assert meta["credits"] == 500 and meta["from_topup"] == 100, "цена и факт разошлись молча"


@pytest.mark.asyncio
async def test_a_covered_charge_has_no_uncovered_field():
    """🔴 ГРАНИЦА. Поле-ноль у почти всех событий только мешает искать настоящие недоборы."""
    session = _Session(quota_remaining=1000, topup=0)

    await _charge(session, 500)

    assert "uncovered" not in session.usage_metadata()


# --- резерв виден рядом с фактом ---------------------------------------------------------- #


def test_the_worker_puts_the_reservation_into_metadata():
    """🔴 ТОЧКА ВЫЗОВА. Поле кладёт ВОРКЕР: репозиторий про резерв не знает и знать не должен.

    Разбираем ДЕРЕВО: подстрока нашлась бы и в комментарии, которым правка объяснена.
    """
    import ast
    import inspect

    from service.services.chat.infrastructure.chat_worker import charging

    tree = ast.parse(inspect.getsource(charging._charge_usage).strip())
    keys = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "reserved_estimate"
    }

    assert keys, "резерв не попадает в метаданные списания — связь «резерв → факт» теряется"


@pytest.mark.asyncio
async def test_worker_metadata_reaches_the_event():
    """⚠️ Метаданные воркера обязаны ДОЕЗЖАТЬ до события: без этого поле есть в коде и нет
    в базе — ровно тот случай, когда правку считают сделанной, а расследовать нечем."""
    session = _Session(quota_remaining=1000, topup=0)

    await _charge(session, 100, metadata={"reserved_estimate": 250, "job_id": "job-1"})

    meta = session.usage_metadata()
    assert meta.get("reserved_estimate") == 250
    assert meta.get("job_id") == "job-1"
