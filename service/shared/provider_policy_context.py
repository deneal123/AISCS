"""Провайдерная политика прогона — сторона ПОТРЕБИТЕЛЯ (сайдкар).

Кого админ выключил и кого заблокировала health-проверка — состояние backend'а (его
БД и Redis). У сайдкара их нет по устройству, поэтому политика приезжает СНИМКОМ в
теле ``/run`` и разворачивается здесь на время прогона.

ContextVar, а не аргумент: политику читают модульные функции глубоко в
мультипровайдерном слое (реестр, фейловер, vector_store), ссылки на запрос у них нет.
У каждой asyncio-задачи свой контекст, поэтому параллельные прогоны не путают политики.

⚠️ ИНВАРИАНТ: снимка НЕТ (``None``) — читаем свой источник; снимок ЕСТЬ и пуст — это
осознанное «никто не выключен». Разница значимая: без неё снятый админом провайдер
снова принимал бы трафик.

``_LAST_SEEN`` — процесс-глобальная память последнего снимка. Она НУЖНА: ``/v1``-шлюз
зовут по OpenAI-протоколу, места под политику там нет, и без этой памяти он остался бы
fail-open. Производящая половина (``build_snapshot``) живёт у backend и сюда НЕ
копируется — иначе у сервисов завелись бы два независимых представления о политике.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Iterator
from contextvars import ContextVar
from typing import Any

_SNAPSHOT: ContextVar[dict[str, frozenset[str]] | None] = ContextVar(
    "gpthub_provider_policy_snapshot", default=None
)

# Последний снимок, ВИДЕННЫЙ процессом (сайдкар). Нужен путям, у которых своего снимка
# нет и быть не может: `/v1`-шлюз зовут memos/ldr/graphify по OpenAI-протоколу, в нём
# места под политику нет. Снимок приезжает с каждым `/run`, поэтому в http-режиме
# кэш держится свежим сам собой — отдельный канал доставки не нужен (а Фаза 3 всё равно
# заменит это владением: политика переедет в сайдкар целиком).
#
# ГРАНИЦА ПРИМЕНИМОСТИ: пока сайдкар не обслужил ни одного `/run`, политика ему НЕИЗВЕСТНА,
# и `/v1` работает как раньше — «запрещённых нет». Это осознанный компромисс, но НЕ немой:
# состояние видно в `/health.provider_policy`. Backend сюда не пишет никогда, поэтому его
# in-process путь этого кэша не касается.
_LAST_SEEN: dict[str, frozenset[str]] | None = None


def _normalize(names: Any) -> frozenset[str]:
    """Имена провайдеров в канонический вид (как их пишет сам provider_policy)."""
    if not isinstance(names, Iterable) or isinstance(names, (str, bytes)):
        return frozenset()
    return frozenset(str(n).strip().lower() for n in names if str(n).strip())


def remember_snapshot(payload: Any) -> None:
    """Запомнить снимок на весь процесс (зовёт сайдкар из ``/run``).

    Так политику получают пути БЕЗ своего снимка — прежде всего ``/v1``: его зовут по
    OpenAI-протоколу, где поля под политику нет. Мусор игнорируем молча: это фоновое
    обогащение, ронять из-за него прогон нельзя.
    """
    global _LAST_SEEN
    if isinstance(payload, dict):
        _LAST_SEEN = {
            "disabled": _normalize(payload.get("disabled")),
            "blocked": _normalize(payload.get("blocked")),
        }


def _resolve(key: str) -> frozenset[str] | None:
    """Снимок запроса → последний виденный процессом → «не знаю» (``None``)."""
    snapshot = _SNAPSHOT.get()
    if snapshot is not None:
        return snapshot[key]
    if _LAST_SEEN is not None:
        return _LAST_SEEN[key]
    return None


def get_disabled() -> frozenset[str] | None:
    """Выключенные админом по снимку; ``None`` = снимка нет, читай свой источник."""
    return _resolve("disabled")


def get_blocked() -> frozenset[str] | None:
    """Заблокированные health-проверкой по снимку; ``None`` = снимка нет."""
    return _resolve("blocked")


def describe() -> dict[str, Any]:
    """Состояние политики для ``/health``: чтобы «политика неизвестна» было ВИДНО."""
    return {
        "known": _LAST_SEEN is not None,
        "disabled": sorted(_LAST_SEEN["disabled"]) if _LAST_SEEN else [],
        "blocked": sorted(_LAST_SEEN["blocked"]) if _LAST_SEEN else [],
    }


@contextlib.contextmanager
def use_snapshot(payload: Any) -> Iterator[None]:
    """Применить снимок на время прогона (сторона сайдкара).

    Не-словарь (в т.ч. ``None`` от старого backend'а) — НЕ ошибка: просто не трогаем
    контекст, и читатели остаются на прежнем поведении.
    """
    if not isinstance(payload, dict):
        yield
        return
    token = _SNAPSHOT.set(
        {
            "disabled": _normalize(payload.get("disabled")),
            "blocked": _normalize(payload.get("blocked")),
        }
    )
    try:
        yield
    finally:
        _SNAPSHOT.reset(token)
