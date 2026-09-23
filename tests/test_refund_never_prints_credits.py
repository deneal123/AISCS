"""Реституция возвращает СНЯТОЕ, а не номинал — иначе она печатает кредиты.

🔴 ЗАМЕРЕНО НА ЖИВОЙ БАЗЕ. Квота исчерпана, докуп-кошелёк 100, цена вызова 500:

    charge(500) → фактически снято 100, метод вернул {"from_topup": 500}
    refund(500) → общий баланс 100 → 500

ЧЕТЫРЕСТА КРЕДИТОВ ИЗ ВОЗДУХА, и достаточно одного сбоя после списания: реституция
запускается именно на этом пути («пользователь оплатил вызов, но не увидел ответ»).

Причин было две, и каждая сама по себе достаточна:
* `charge()` считал `from_topup = credits - from_subscription`, то есть ЖЕЛАЕМОЕ. Само
  списание обрезалось `GREATEST(0, …)`, а в ответ и в `billing_events` уходил номинал;
* `_charge_usage()` возвращал `int(credits)` — цену вызова, — и на этом числе построены и
  реституция, и стоимость хода, которую видит человек.

⚠️ Недобор теперь ещё и НАЗЫВАЕТСЯ: списали меньше, чем стоило, — значит разницу заплатила
платформа. Молчание здесь означало бы, что деньги теряются без следа.
"""

from __future__ import annotations

import logging

import pytest

_LOGGER_NAME = "service.services.billing.persistence.billing_repository"


@pytest.fixture(autouse=True)
def _logs_reach_caplog(caplog):
    """Логгер `service` объявлен с `propagate: False` — цепляем хендлер прямо к нему."""
    logger = logging.getLogger(_LOGGER_NAME)
    logger.addHandler(caplog.handler)
    previous = logger.level
    logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(previous)


class _Session:
    """Двойник сессии: отвечает на каждый SQL по его характерному фрагменту.

    ⚠️ Различаем запросы ПО ТЕКСТУ, потому что именно порядок и состав чтений здесь и есть
    предмет проверки: без чтения докупа под блокировкой арифметика снова станет догадкой.
    """

    def __init__(self, *, quota_remaining: int, topup: int):
        self.quota_remaining = quota_remaining
        self.topup = topup
        self.deducted_subscription = 0
        self.deducted_topup = 0
        self.locked_topup = False
        self.events: list[dict] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}

        class _Result:
            def __init__(self, row=None):
                self._row = row

            def first(self):
                return self._row

            def scalar(self):
                return self._row[0] if self._row else None

        if 'limit" - used' in sql or '("limit" - used)' in sql:
            return _Result((self.quota_remaining,))
        if "topup_credit_balance FROM profile" in sql and "FOR UPDATE" in sql:
            self.locked_topup = True
            return _Result((self.topup,))
        if "SET used = used +" in sql:
            self.deducted_subscription += int(params.get("amt") or 0)
            return _Result()
        if "topup_credit_balance = GREATEST" in sql:
            self.deducted_topup += int(params.get("amt") or 0)
            return _Result()
        if "billing_events" in sql and "INSERT" in sql:
            self.events.append(dict(params))
            return _Result()
        return _Result()

    async def commit(self):
        return None


async def _charge(session, credits: int):
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
        session=session,
    )


# --- charge отчитывается фактом ----------------------------------------------------------- #


@pytest.mark.asyncio
async def test_charge_reports_what_it_actually_took():
    """🔴 ГЛАВНОЕ. Баланса на 100, цена 500 — в ответе должно быть 100, не 500."""
    session = _Session(quota_remaining=0, topup=100)

    result = await _charge(session, 500)

    assert result["from_topup"] == 100, (
        "метод отчитался о номинале — на этом числе построена реституция, и она напечатает "
        "разницу из воздуха"
    )
    # ⚠️ И в СУБД уходит ровно доступное, а не номинал: прежде туда уезжало 500 и обрезалось
    # `GREATEST(0, …)`. Обрезка осталась страховкой, но теперь она не единственная защита —
    # арифметика знает остаток, а не догадывается о нём.
    assert session.deducted_topup == 100, "в списание снова уходит номинал вместо доступного"


@pytest.mark.asyncio
async def test_the_topup_balance_is_read_under_a_lock():
    """🔴 Без блокировки строки два параллельных списания увидели бы один и тот же докуп и
    оба сочли бы его своим — та же гонка, от которой квота читается `FOR UPDATE`."""
    session = _Session(quota_remaining=0, topup=100)

    await _charge(session, 500)

    assert session.locked_topup, "остаток докупа прочитан без FOR UPDATE"


@pytest.mark.asyncio
async def test_a_covered_charge_is_unchanged():
    """🔴 ГРАНИЦА. Хватает баланса — поведение прежнее, до последнего кредита."""
    session = _Session(quota_remaining=0, topup=1000)

    result = await _charge(session, 500)

    assert result == {"from_subscription": 0, "from_topup": 500}


@pytest.mark.asyncio
async def test_the_subscription_is_spent_first():
    """⚠️ Порядок кошельков не меняем: квота истекает, докуп нет — тратить надо истекающее."""
    session = _Session(quota_remaining=300, topup=1000)

    result = await _charge(session, 500)

    assert result == {"from_subscription": 300, "from_topup": 200}


@pytest.mark.asyncio
async def test_an_uncovered_charge_is_logged(caplog):
    """🔴 Списали меньше, чем стоило — разницу заплатила платформа. Это ДЕНЬГИ, и они не
    должны теряться без следа в логе."""
    session = _Session(quota_remaining=0, topup=100)

    with caplog.at_level("WARNING"):
        await _charge(session, 500)

    messages = " ".join(r.getMessage().lower() for r in caplog.records)
    assert "списано меньше стоимости" in messages
    assert "не покрыто 400" in messages, "размер недобора не назван — сверять будет нечем"


@pytest.mark.asyncio
async def test_a_covered_charge_says_nothing(caplog):
    """🔴 ГРАНИЦА. Шум в логе на штатном списании прячет настоящие недоборы."""
    session = _Session(quota_remaining=1000, topup=0)

    with caplog.at_level("WARNING"):
        await _charge(session, 500)

    assert not [r for r in caplog.records if "списано меньше" in r.getMessage().lower()]


# --- повторная доставка -------------------------------------------------------------------- #


def test_a_redelivered_job_reports_zero():
    """🔴 Celery редоставляет задачу, если воркер умер после коммита списания. В ЭТОЙ попытке
    денег не двигали — значит и возвращать нечего.

    Отдай мы сумму оригинального списания, реституция при следующем сбое вернула бы ЧУЖИЕ
    деньги: списание было в прошлой попытке, а возврат ушёл бы по этой.
    """
    from service.services.billing.domain.charge_math import actually_charged

    assert actually_charged({"from_subscription": 0, "from_topup": 0, "idempotent": True}) == 0
    # ⚠️ Проверяем и случай, когда рядом с признаком лежат НЕНУЛЕВЫЕ суммы: признак сильнее.
    assert actually_charged({"from_subscription": 700, "from_topup": 300, "idempotent": True}) == 0


def test_a_missing_or_broken_result_reports_zero():
    """⚠️ Ответа нет (сбой, двойник, старый вызов) — возвращать нечего. Догадка здесь стоила
    бы реальных денег, а ноль лишь оставит реституцию без работы."""
    from service.services.billing.domain.charge_math import actually_charged

    assert actually_charged(None) == 0
    assert actually_charged("не словарь") == 0
    assert actually_charged({}) == 0


# --- точка вызова: что уходит в реституцию ------------------------------------------------ #


def test_the_worker_returns_the_actual_charge_not_the_price():
    """🔴 ТОЧКА ВЫЗОВА. Правило в репозитории верно, а воркер возвращал `int(credits)` —
    цену вызова. Реституция и стоимость хода для человека берутся ИМЕННО оттуда.

    Разбираем ДЕРЕВО: подстрока нашлась бы и в комментарии, которым я правку объяснил.
    """
    import ast
    import inspect

    # ⚠️ Биллинг хода живёт в `chat_worker/charging.py` — там же, где и правило про факт.
    from service.services.chat.infrastructure.chat_worker import charging

    tree = ast.parse(inspect.getsource(charging._charge_usage).strip())
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return) and n.value is not None]
    via_domain = [
        node
        for node in returns
        if isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", "") == "actually_charged"
    ]

    assert via_domain, (
        "воркер не возвращает результат через `actually_charged` — значит отдаёт номинал, "
        "и реституция снова напечатает разницу"
    )
    # ⚠️ И НИ ОДИН возврат не отдаёт цену напрямую: одна забытая ветка вернула бы номинал,
    # а ветвлений в этой функции хватает (идемпотентность, нулевая цена, отказ).
    price_returns = [
        node for node in returns if isinstance(node.value, ast.Call) and _is_int_credits(node.value)
    ]
    assert not price_returns, "какая-то ветка возвращает `int(credits)` — это номинал, не факт"


def _is_int_credits(call: object) -> bool:
    """`int(credits)` — тот самый номинал, из-за которого печатались кредиты."""
    import ast

    return (
        isinstance(call, ast.Call)
        and getattr(call.func, "id", "") == "int"
        and len(call.args) == 1
        and getattr(call.args[0], "id", "") == "credits"
    )
