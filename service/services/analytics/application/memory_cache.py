"""Кэш дашборда семантической памяти (MemOS) в Redis.

Замер: вызов в MemOS занимает 124-172 мс на КАЖДОЕ открытие панели — сеть до сайдкара,
прогрев не помогает (для сравнения факты из Postgres после прогрева отдаются за 3 мс).
Фронт запрашивает дашборд вторым запросом, после фактов, поэтому блок семантической
памяти появляется заметно позже остальной панели.

🔴 TTL здесь НЕ единственный механизм свежести. Содержимое MemOS меняется после каждого
разговора; кэш только по времени означал бы, что человек поговорил, открыл панель и
увидел прежние счётчики — со стороны это «память не сохранилась», то есть ошибка хуже
устраняемой задержки. Основной механизм — СБРОС ПРИ ЗАПИСИ (`invalidate`), TTL остаётся
страховкой на изменения мимо нас (правки в MemOS со стороны, ручная чистка).

Кэш НЕОБЯЗАТЕЛЕН: без Redis всё работает как раньше, просто медленнее. Поэтому каждая
функция здесь молча деградирует, а не бросает.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

TTL_SEC = 300


def key(scoped_user_id: str) -> str:
    """Ключ на ПОЛЬЗОВАТЕЛЯ: чужие счётчики памяти — это утечка, а не неточность."""
    return f"memory:dashboard:{scoped_user_id}"


def _redis():
    """Клиент Redis или None."""
    try:
        from service.infrastructure.cache.redis_manager import RedisManager
        from service.settings import config

        manager = RedisManager(config.redis)
        return manager.get_client() if manager.enabled else None
    except Exception:  # noqa: BLE001
        logger.debug("redis для кэша памяти недоступен", exc_info=True)
        return None


async def get(scoped_user_id: str) -> dict[str, Any] | None:
    client = _redis()
    if client is None:
        return None
    try:
        raw = await client.get(key(scoped_user_id))
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001 — в Redis мог остаться мусор от прежней версии
        logger.debug("чтение кэша памяти не удалось", exc_info=True)
        return None


async def put(scoped_user_id: str, value: dict[str, Any]) -> None:
    client = _redis()
    if client is None:
        return
    try:
        await client.set(key(scoped_user_id), json.dumps(value, ensure_ascii=False), ex=TTL_SEC)
    except Exception:  # noqa: BLE001
        logger.debug("запись кэша памяти не удалась", exc_info=True)


async def invalidate(scoped_user_id: str) -> None:
    """Сбросить после записи в MemOS — иначе панель покажет «память не изменилась»."""
    client = _redis()
    if client is None:
        return
    try:
        await client.delete(key(scoped_user_id))
    except Exception:  # noqa: BLE001
        logger.debug("сброс кэша памяти не удался", exc_info=True)
