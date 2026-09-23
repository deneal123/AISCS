"""Агрегированный каталог моделей всех провайдеров: кэш с TTL и роутинг по владельцу.

Каталог — это union списков моделей ВСЕХ сконфигурированных провайдеров плюс индекс
`model_id → провайдер`. Индекс нужен, чтобы выбранная модель уходила своему владельцу,
а не подменялась чужой при фейловере.

⚠️ Активного провайдера читаем ЧЕРЕЗ МОДУЛЬ (`active.ACTIVE_PROVIDER`), а не импортом
имени: его меняет `active.rebuild_provider()` при замене ключа в админке, и связанное
на импорте значение осталось бы старым молча. См. докстринг `active.py`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .. import active
from ..registry import build_model_catalog, get_provider_module

logger = logging.getLogger(__name__)

# Кэш агрегированного каталога моделей (union по провайдерам) + индекс model→owner.
# TTL, чтобы не дёргать все провайдерские list-эндпоинты на каждый вызов/пикер.
_CATALOG_CACHE: dict = {"list": [], "index": {}, "expires": 0.0, "initialized": False}
_CATALOG_TTL = 180.0
# После неудачного/пустого рефреша — короткий повтор: не хаммерим мёртвые провайдеры
# каждым запросом, но и не ждём полный TTL до следующей попытки.
_CATALOG_RETRY_TTL = 30.0
# Бюджет на СИНХРОННЫЙ рефреш при наличии устаревшего списка: не успели в бюджет —
# отдаём устаревший (serve-stale) без долгой блокировки запроса.
_CATALOG_REFRESH_BUDGET = 6.0


# Замок single-flight: одновременная перестройка каталога должна идти ОДНА.
#
# ⚠️ ХРАНИМ ВМЕСТЕ С ПЕТЛЁЙ, а не просто `asyncio.Lock()` на модуле. Lock привязывается к
# event loop при первом использовании и из другой петли бросает RuntimeError. Сайдкар
# живёт под uvicorn с одной петлёй, но этот же модуль исторически исполнялся и там, где
# петля своя на задачу (см. предупреждение про celery в докстринге ниже) — и модульный
# замок стал бы там источником загадочных падений. Петля сменилась → берём новый замок:
# single-flight в такой среде вырождается, но НИЧЕГО НЕ ЛОМАЕТ.
_REBUILD_LOCK: tuple[Any, asyncio.Lock] | None = None


def _rebuild_lock() -> asyncio.Lock:
    global _REBUILD_LOCK
    loop = asyncio.get_running_loop()
    if _REBUILD_LOCK is None or _REBUILD_LOCK[0] is not loop:
        _REBUILD_LOCK = (loop, asyncio.Lock())
    return _REBUILD_LOCK[1]


def invalidate_model_catalog() -> None:
    """Drop aggregate provenance after a provider configuration generation changes."""
    _CATALOG_CACHE.update(list=[], index={}, expires=0.0, initialized=False)


async def _rebuild_catalog() -> tuple[list[str], dict[str, str]]:
    now = time.monotonic()
    try:
        aggregated, index = await build_model_catalog(active.ACTIVE_PROVIDER)
    except Exception:  # noqa: BLE001
        logger.warning("model catalog build failed", extra={"failure_code": "internal"})
        # Придержим повтор и отдадим последний известный список (не пустой).
        _CATALOG_CACHE["expires"] = now + _CATALOG_RETRY_TTL
        return _CATALOG_CACHE["list"], _CATALOG_CACHE["index"]
    # Successful discovery is authoritative even when every provider returned an
    # empty inventory. Transport failures are represented by typed stale/static
    # snapshots before this aggregate is built, so an empty aggregate is no longer
    # an ambiguous failure signal.
    _CATALOG_CACHE.update(
        list=aggregated,
        index=index,
        expires=now + _CATALOG_TTL,
        initialized=True,
    )
    return aggregated, index


async def get_model_catalog() -> tuple[list[str], dict[str, str]]:
    """Агрегированный каталог моделей с TTL: (список чат-моделей, model_id → провайдер).

    Только chat-совместимые модели (эмбеддеры/аудио/картинки исключены). Индекс
    владельца нужен, чтобы показывать реального провайдера у id без префикса
    (напр. «gpt-5.5» → openai).

    Рефреш СИНХРОННЫЙ. ⚠️ Фоновый (``asyncio.create_task``) serve-while-revalidate не
    работает в celery-воркерах: там loop-per-task — фоновая задача умирает вместе с
    петлёй, а ``expires`` уже сдвигался вперёд, поэтому каталог фактически не обновлялся
    весь TTL (протухший список отдавался до рестарта процесса), а флаг ``refreshing`` мог
    залипнуть. Здесь при наличии устаревшего списка рефреш ограничен бюджетом и на
    таймауте отдаёт устаревший (serve-stale), а ``expires`` двигается только при
    успехе/коротком retry — так это корректно и в API-процессе, и в воркере.
    """
    now = time.monotonic()
    # A successful empty discovery is still a warm, authoritative cache entry.
    have = bool(_CATALOG_CACHE.get("initialized") or _CATALOG_CACHE["list"])
    if have and now < _CATALOG_CACHE["expires"]:
        return _CATALOG_CACHE["list"], _CATALOG_CACHE["index"]

    # ⚠️ SINGLE-FLIGHT. Замка не было вовсе, и в МОМЕНТ ИСТЕЧЕНИЯ TTL все одновременные
    # запросы уходили перестраивать каталог каждый сам: перестройка — это `gather` по
    # ПЯТИ провайдерам с таймаутом на каждого, то есть самый дорогой момент совпадал с
    # самым многолюдным. Отсутствие замка было задокументировано как «гонки безвредны» —
    # это верно про идемпотентность записи и неверно про дублирование сетевой работы.
    lock = _rebuild_lock()

    if have:
        # Устаревшее есть. Кто-то уже обновляет → отдаём его НЕМЕДЛЕННО, не вставая в
        # очередь: ждать чужого рефреша хуже, чем отдать список трёхминутной давности.
        if lock.locked():
            return _CATALOG_CACHE["list"], _CATALOG_CACHE["index"]
        async with lock:
            try:
                return await asyncio.wait_for(_rebuild_catalog(), timeout=_CATALOG_REFRESH_BUDGET)
            except TimeoutError:
                _CATALOG_CACHE["expires"] = now + _CATALOG_RETRY_TTL
                return _CATALOG_CACHE["list"], _CATALOG_CACHE["index"]

    # Холодный старт (кэш пуст) — отдавать нечего, ждём сборку. Здесь очередь как раз
    # уместна: все ждут ОДНУ сборку вместо того, чтобы устроить веер по провайдерам.
    async with lock:
        # Пока стояли в очереди, лидер мог всё собрать — тогда сборка не нужна.
        if (
            _CATALOG_CACHE.get("initialized") or _CATALOG_CACHE["list"]
        ) and time.monotonic() < _CATALOG_CACHE["expires"]:
            return _CATALOG_CACHE["list"], _CATALOG_CACHE["index"]
        return await _rebuild_catalog()


def reorder_owner_first(order: list[str], model: str | None, index: dict[str, str]) -> list[str]:
    """Поставить провайдера-владельца модели первым (точный роутинг без подмены)."""
    if not model:
        return order
    owner = index.get(model)
    if owner and getattr(get_provider_module(owner), "OPENAI_CLIENT", None) is not None:
        return [owner] + [p for p in order if p != owner]
    return order
