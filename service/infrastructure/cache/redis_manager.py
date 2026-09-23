from __future__ import annotations

import logging

from redis.asyncio import Redis

from service.settings import RedisConfig

logger = logging.getLogger(__name__)


def is_async_client(client) -> bool:
    """Асинхронный ли клиент Redis. Судим по `execute_command` НА ТИПЕ.

    🔴 НЕ ПО КОМАНДЕ. `inspect.iscoroutinefunction(Redis.xtrim)` на `redis.asyncio`
    отвечает ЛОЖЬ — команды там обычные методы, возвращающие корутину. Замерено на живом
    клиенте: `xadd`, `xtrim`, `xinfo_stream`, `xinfo_groups`, `scan_iter` дают `False` У
    ОБОИХ клиентов, и только `execute_command` их различает.

    Цена ошибки — не исключение, а МОЛЧАНИЕ: асинхронный клиент уходил в `to_thread`, тот
    возвращал НЕ ДОЖДАННУЮ корутину, и команда не исполнялась вовсе. Живым прогоном
    поймано дважды: привязка песочницы не писалась и не читалась (панель плодила
    контейнеры), а периодическая обрезка потоков чата не обрезала НИЧЕГО — 112 потоков в
    dev-базе, самый длинный 992 записи при потолке 1000, и остановить его рост было нечем.

    ⚠️ ПРАВИЛО ОДНО НА ВЕСЬ СЕРВИС. Две его копии — ровно тот случай, когда одна отстаёт и
    ошибка возвращается: этот же дефект чинился в клиенте песочницы, а в помощнике потоков
    остался жить ещё в семи местах.
    """
    import inspect

    return inspect.iscoroutinefunction(getattr(type(client), "execute_command", None))


class RedisManager:
    """Lazily creates and manages a Redis asyncio client."""

    def __init__(self, config: RedisConfig) -> None:
        self._config = config
        self._client: Redis | None = None

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def get_client(self) -> Redis:
        if not self.enabled:
            raise RuntimeError("Redis is disabled via configuration")

        if self._client is None:
            logger.info(
                "Initializing Redis client (host=%s, port=%s, db=%s)",
                self._config.host,
                self._config.port,
                self._config.db,
            )
            self._client = Redis(
                host=self._config.host,
                port=self._config.port,
                db=self._config.db,
                password=self._config.password or None,
                ssl=self._config.settings.use_ssl,
                decode_responses=self._config.settings.decode_responses,
                health_check_interval=self._config.settings.health_check_interval,
            )
        return self._client

    async def ping(self) -> bool:
        if not self.enabled:
            return False
        client = self.get_client()
        try:
            return bool(await client.ping())
        except Exception:  # noqa: BLE001
            logger.exception("Redis ping failed")
            return False

    async def close(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.close()
            await self._client.connection_pool.disconnect()
            logger.info("Redis client closed")
        except Exception:  # noqa: BLE001
            logger.exception("Error while closing Redis client")
        finally:
            self._client = None
