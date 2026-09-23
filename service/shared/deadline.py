"""Дедлайн прогона: сколько времени осталось и хватит ли его, чтобы ОТВЕТИТЬ.

⚠️ ЗАЧЕМ ОТДЕЛЬНОЕ ПОНЯТИЕ. Внешний `asyncio.wait_for` — это стоп, а не бюджет: он умеет
только оборвать, причём в произвольной точке. Из-за этого одна медленная выборка успевала
съесть время, нужное на формулировку ответа, а сам обрыв уничтожал уже накопленный счёт.

🔴 РЕЗЕРВ НА ФИНАЛИЗАЦИЮ — главное здесь. Прогон обязан остановиться НЕ на дедлайне, а
раньше: так, чтобы осталось на последний вызов модели. Иначе поведение при исчерпании
времени — «ничего», хотя работа на тысячи токенов уже оплачена.

Живёт в ContextVar, а не в аргументах: дедлайн нужен в глубине цикла инструментов, и
протаскивать его через шесть слоёв значило бы менять сигнатуры ради одного числа. Ставится
на входе прогона, снимается вместе с задачей.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

# Сколько времени бережём под финальный вызов модели. Один вызов chat/completions с
# коротким ответом укладывается в это с запасом; меньше — и «отвечай тем, что есть» само
# не успеет.
DEFAULT_FINALIZATION_RESERVE_SEC = 45.0


@dataclass(frozen=True, slots=True)
class RunDeadline:
    """Бюджет времени одного прогона. `limit_sec=None` — дедлайна нет."""

    started_monotonic: float
    limit_sec: float | None
    finalization_reserve_sec: float = DEFAULT_FINALIZATION_RESERVE_SEC

    @classmethod
    def start(
        cls, limit_sec: float | None, reserve_sec: float = DEFAULT_FINALIZATION_RESERVE_SEC
    ) -> RunDeadline:
        return cls(time.monotonic(), limit_sec, reserve_sec)

    def remaining(self) -> float | None:
        """Секунд до дедлайна. `None` — дедлайна нет."""
        if not self.limit_sec or self.limit_sec <= 0:
            return None
        return self.limit_sec - (time.monotonic() - self.started_monotonic)

    def clamp(self, want_sec: float) -> float:
        """Сколько дать операции: не больше, чем остаётся сверх резерва.

        ⚠️ Возвращает МИНИМУМ 1 секунду, а не ноль: нулевой таймаут превратил бы «мало
        времени» в «операция всегда падает», и вместо деградации получился бы отказ.
        """
        left = self.remaining()
        if left is None:
            return want_sec
        return max(1.0, min(want_sec, left - self.finalization_reserve_sec))

    def must_finalize(self) -> bool:
        """Пора заканчивать: на новый шаг времени уже нет, на ответ — ещё есть."""
        left = self.remaining()
        return left is not None and left <= self.finalization_reserve_sec


_CURRENT: ContextVar[RunDeadline | None] = ContextVar("run_deadline", default=None)


def current() -> RunDeadline | None:
    return _CURRENT.get()


def remaining() -> float | None:
    deadline = _CURRENT.get()
    return deadline.remaining() if deadline else None


def clamp(want_sec: float) -> float:
    """Ограничить желаемый таймаут остатком бюджета. Без дедлайна — вернуть как есть."""
    deadline = _CURRENT.get()
    return deadline.clamp(want_sec) if deadline else want_sec


def must_finalize() -> bool:
    deadline = _CURRENT.get()
    return bool(deadline and deadline.must_finalize())


@contextmanager
def use_deadline(deadline: RunDeadline | None):
    token = _CURRENT.set(deadline)
    try:
        yield deadline
    finally:
        _CURRENT.reset(token)
