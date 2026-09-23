"""Надбавка берётся за ОКАЗАННУЮ услугу, а не за факт вызова инструмента.

🔴 ЗАМЕРЕНО НА ЖИВОМ СТЕКЕ. Вопрос «какая сейчас ключевая ставка ЦБ» с включённым поиском:
все поисковые движки отвалились по таймауту (`TimeoutError` в логах сайдкара), инструмент
честно вернул «поиск недоступен» — и с человека всё равно взяли надбавку 833 кредита из
1135 за ход. Заплачено за услугу, которой не было.

Причина: надбавка ставилась по ФАКТУ ВЫЗОВА (`_billable_tools_meta` в цикле раундов), а
вызов и результат — разные вещи. «Ничего не найдено» — законный результат поиска, за него
платят; «поиск недоступен» — отказ, платить не за что.

⚠️ СЧИТАЕМ, А НЕ СТАВИМ ФЛАГ. Одна надбавка покрывает несколько вызовов (у песочницы —
шесть инструментов на одно имя, поиск модель зовёт по два-три раза), и «был хоть один
отказ → бесплатно» превратилось бы в недобилл: упавший первый вызов отменил бы плату за
успешный второй. Имя тарифицируется, пока вызовов БОЛЬШЕ, чем отказов.

⚠️ ПОЧЕМУ ContextVar С МУТИРУЕМЫМ ОБЪЕКТОМ. Контракт инструмента — строка, и разбирать её
в цикле раундов значило бы угадывать отказ по тексту. Раунд исполняется в дочерних задачах
(`asyncio.gather`), а они получают КОПИЮ контекста: присваивание наверх не вернулось бы, а
дозапись в общий объект — видна. Та же причина, по которой так собираются ссылки
(`found_sources`), и тот же повод требовать от теста ПАРАЛЛЕЛЬНОГО прогона.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_CURRENT: ContextVar[dict[str, dict[str, int]] | None] = ContextVar(
    "gpthub_unbilled_calls", default=None
)


@contextmanager
def collect():
    """Включить учёт вызовов и отказов на время прогона."""
    ledger: dict[str, dict[str, int]] = {"calls": {}, "waived": {}}
    token = _CURRENT.set(ledger)
    try:
        yield ledger
    finally:
        _CURRENT.reset(token)


def _bump(bucket: str, billing_name: str) -> None:
    ledger = _CURRENT.get()
    if ledger is None or not billing_name:
        return
    counts = ledger[bucket]
    counts[str(billing_name)] = counts.get(str(billing_name), 0) + 1


def waive(billing_name: str) -> None:
    """Отметить ОТКАЗ: услуга не оказана. Вне прогона — молча ничего."""
    _bump("waived", billing_name)


def count_call(billing_name: str) -> None:
    """Отметить состоявшийся вызов платного инструмента."""
    _bump("calls", billing_name)


def billable(billing_name: str) -> bool:
    """Заработана ли надбавка: были вызовы, и не все они кончились отказом.

    Вне прогона (учёт не включён) — ДА: молчаливая бесплатность опаснее лишнего счёта,
    её никто не заметит, а деньги теряются на каждом ходу.
    """
    ledger = _CURRENT.get()
    if ledger is None:
        return True
    name = str(billing_name)
    return ledger["calls"].get(name, 0) > ledger["waived"].get(name, 0)
