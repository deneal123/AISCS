"""Детекция аномальной скорости трат (Фаза 5).

Накапливает потраченные кредиты в текущем окне (Redis) и сигнализирует, если
расход превысил порог. Только детективный контроль (флаг в billing_events),
не блокировка — чтобы не бить ложных срабатываний по легитимным всплескам.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def accumulate_spend(
    redis_client, *, user_id: str | None, credits: int, window_seconds: int, now: float
) -> int | None:
    """Прибавить траты к окну и вернуть суммарный расход за окно.

    None — Redis недоступен/сбой/нет данных (аномалию не проверяем, fail-open).
    """
    if redis_client is None or not user_id or int(credits) <= 0 or window_seconds <= 0:
        return None
    bucket = int(now // window_seconds)
    key = f"spendrate:{user_id}:{bucket}"
    try:
        total = int(await redis_client.incrby(key, int(credits)))
        if total <= int(credits):  # первая запись окна — выставляем TTL
            await redis_client.expire(key, window_seconds)
        return total
    except Exception:
        logger.debug("Spend-rate accumulation failed", exc_info=True)
        return None
