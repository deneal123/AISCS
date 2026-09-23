"""Арифметика списания: с какого кошелька сколько снять и сколько снялось на самом деле.

Доменное правило, а не деталь репозитория: оно про ДЕНЬГИ, и проверять его надо напрямую,
без подмены сессии и SQL. Репозиторий остаётся транспортом — читает остатки под блокировкой
и исполняет то, что решено здесь.

🔴 ПОЧЕМУ ЭТО ВЫНЕСЕНО ИМЕННО ТЕПЕРЬ. Распределение считалось на месте так:

    from_subscription = min(credits, max(0, remaining))
    from_topup = credits - from_subscription

то есть второе слагаемое было ЖЕЛАЕМЫМ, а не возможным: остаток докуп-кошелька никто не
читал. Само списание обрезалось `GREATEST(0, …)` в SQL, но в ответ метода и в
`billing_events` уходил номинал — и на этом номинале построена реституция.

Замер на живой базе: квота исчерпана, докуп 100, цена вызова 500 → снято 100, отчёт «снято
500», возврат 500 → общий баланс 100 → 500. ЧЕТЫРЕСТА КРЕДИТОВ ИЗ ВОЗДУХА за один сбой
после списания.
"""

from __future__ import annotations

from typing import NamedTuple


class ChargeSplit(NamedTuple):
    """Как разложилось списание. `uncovered` > 0 означает, что разницу заплатила платформа."""

    from_subscription: int
    from_topup: int
    uncovered: int

    @property
    def total(self) -> int:
        return self.from_subscription + self.from_topup


def split_charge(credits: int, quota_remaining: int, topup_available: int) -> ChargeSplit:
    """Разложить списание по кошелькам, не выходя за их остатки.

    ⚠️ ПОРЯДОК КОШЕЛЬКОВ НЕСУЩИЙ: сначала квота подписки, потом докуп. Квота истекает в
    конце периода, докуп — нет, поэтому тратить надо истекающее; обратный порядок молча
    сжигал бы у человека постоянные кредиты, оставляя пропадать временные.

    ⚠️ `uncovered` возвращается ОТДЕЛЬНЫМ ЧИСЛОМ, а не прячется в сумме: «списали меньше,
    чем стоило» — это деньги, которые заплатила платформа, и молчание о них означало бы, что
    они теряются без следа.
    """
    price = max(0, int(credits))
    if price == 0:
        return ChargeSplit(0, 0, 0)
    from_subscription = min(price, max(0, int(quota_remaining)))
    from_topup = min(price - from_subscription, max(0, int(topup_available)))
    return ChargeSplit(from_subscription, from_topup, price - from_subscription - from_topup)


def actually_charged(charge_result: object) -> int:
    """Сколько денег РЕАЛЬНО ушло, по ответу `BillingRepository.charge`.

    🔴 На этом числе висят две вещи, и обе про деньги: реституция при сбое после списания
    (иначе она вернёт больше, чем сняла) и стоимость хода, которую видит человек. Раньше
    вызывающий брал номинал — цену вызова, — то есть в обоих случаях число было завышенным.

    ⚠️ Ответ повторной доставки (`{"idempotent": True}`) даёт НОЛЬ: в этой попытке денег не
    двигали, и возвращать «чужое» списание предыдущей попытки нельзя.
    """
    if not isinstance(charge_result, dict):
        return 0
    if charge_result.get("idempotent"):
        return 0
    return int(charge_result.get("from_subscription") or 0) + int(
        charge_result.get("from_topup") or 0
    )
