"""Сборка снимка провайдерной политики для тела ``/run`` — сторона ПРОИЗВОДИТЕЛЯ.

Кого админ выключил чекбоксом и кого заблокировала health-проверка — состояние
backend'а: оно живёт в его БД и Redis. У сайдкара их нет по устройству, поэтому
политика едет к нему СНИМКОМ в теле запроса.

Здесь только производящая половина. Потребляющая (ContextVar прогона, процессная
память для путей без своего снимка, чтение `get_disabled`/`get_blocked`) живёт в
сайдкаре и backend'у не нужна — копировать её сюда нельзя намеренно: он завёл бы
свой процесс-глобальный кэш политики, который разошёлся бы с сайдкарным невидимо.

Раньше обе половины лежали в одном модуле общего пакета. Это и была самая резкая
асимметрия того пакета: backend вызывал ровно одну функцию из десяти.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _normalize(names: Any) -> frozenset[str]:
    """Имена провайдеров в канонический вид (как их пишет сам provider_policy)."""
    if not isinstance(names, Iterable) or isinstance(names, (str, bytes)):
        return frozenset()
    return frozenset(str(n).strip().lower() for n in names if str(n).strip())


def build_snapshot(*, disabled: Any = None, blocked: Any = None) -> dict[str, list[str]]:
    """Собрать сериализуемый снимок для тела ``/run``.

    ⚠️ Инвариант, который обязаны понимать обе стороны: снимка НЕТ (поле отсутствует) —
    сайдкар читает свой источник; снимок ЕСТЬ и пуст — это осознанное «никто не
    выключен». Поэтому функция всегда возвращает ОБА ключа, даже пустыми.
    """
    return {
        "disabled": sorted(_normalize(disabled)),
        "blocked": sorted(_normalize(blocked)),
    }
