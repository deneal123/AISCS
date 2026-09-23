"""Асинхронный Redis сайдкара — для его СОБСТВЕННОГО операционного состояния.

Сайдкар stateless по бизнес-данным: история, память и ссылки на файлы приезжают в теле
запроса, в PG/MinIO backend'а он не ходит. Но своё операционное состояние у него есть —
кэш сжатия контекста, здоровье провайдеров, OAuth-токены — и его незачем терять на
каждом рестарте.

Почему свой модуль, а не импорт `service.infrastructure.cache.redis_manager`: этого
модуля в сайдкаре не существует. Импорт стоял под `except`, молча падал, и кэш сжатия
был мёртв — каждое сжатие заново гоняло map-reduce по ЛЛМ, то есть мы платили за одну и
ту же работу повторно.

Клиент АСИНХРОННЫЙ (в отличие от синхронного в `circuit_breaker`): там sync выбран из-за
celery, который создаёт новый event loop на каждую задачу; здесь долгоживущий uvicorn с
одним циклом, и async-клиент проще — вызывающий уже пишет `await client.get(...)`.

Fail-open: Redis не сконфигурен или недоступен → `None`, вызывающий работает без кэша.
"""

from __future__ import annotations

import logging

from service.settings import config

logger = logging.getLogger(__name__)

_client = None
_ready = False


def get_redis():
    """Лениво поднять async-Redis из конфига. ``None`` — работаем без него."""
    global _client, _ready
    if _ready:
        return _client
    _ready = True
    try:
        if not getattr(config.redis, "enabled", False):
            logger.info("redis: не сконфигурен (REDIS__ENABLED пуст) — работаем без кэша")
            return None
        import redis.asyncio as aioredis

        _client = aioredis.from_url(config.redis.dsn, decode_responses=True)
    except Exception:  # noqa: BLE001 — Redis необязателен, вызывающий деградирует
        logger.warning("redis unavailable", extra={"failure_code": "unavailable"})
        _client = None
    return _client
