"""Персональный канал уведомлений пользователя (Redis pub/sub).

⚠️ ПОЧЕМУ PUB/SUB, А НЕ STREAMS. Джобы чата едут Redis Streams — с consumer-group,
replay и PEL, потому что там доставка ГАРАНТИРОВАННАЯ (потеря чанка = дыра в ответе).
Здесь задача другая: сказать онлайн-клиенту «перезапроси баланс». Если пользователь
офлайн, событие терять МОЖНО — он и так перезапросит баланс при следующем открытии
страницы. Гарантии не нужны, а значит не нужна и их цена: pub/sub — fire-and-forget,
без групп, ключей PEL и очистки.

⚠️ ЭТО ОПТИМИЗАЦИЯ, А НЕ ИСТОЧНИК ПРАВДЫ. Баланс всегда читается живьём из БД
(`GET /api/billing/balance`). Канал лишь подсказывает фронту, КОГДА перечитать, чтобы
пополнение админом (оно происходит вне сессии пользователя, и ни ответ модели, ни фокус
вкладки его не триггерят) не ждало ни таймера, ни действия пользователя.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Типы событий канала. Строка — часть контракта с фронтом, менять синхронно.
EVENT_BALANCE_REFRESH = "balance_refresh"


def user_events_channel(user_id: str) -> str:
    """Имя pub/sub-канала персональных событий пользователя.

    Одно место на publisher и подписчика: разъедутся — пуш молча не дойдёт, а баланс
    «снова тормозит». Держим здесь, импортируют обе стороны.
    """
    return f"user:{user_id}:events"


async def publish_user_event(redis_client: Any, user_id: str, event_type: str, **data: Any) -> None:
    """Отправить событие в персональный канал. Полностью fail-soft.

    ⚠️ ОТКАЗ НЕ ДОЛЖЕН ЛОМАТЬ ВЫЗЫВАЮЩЕГО. Публикуется это ПОСЛЕ денежной операции
    (пополнение уже в БД и закоммичено). Упади pub/sub — пользователь просто увидит
    баланс чуть позже, как и раньше; ронять из-за этого успешный запрос админа нельзя.
    """
    if redis_client is None or not user_id:
        return
    try:
        payload = json.dumps({"type": event_type, **data})
        await redis_client.publish(user_events_channel(user_id), payload)
    except Exception:  # noqa: BLE001 — оптимизация уведомления, не критичный путь
        logger.debug("user_events: publish failed for user=%s", user_id, exc_info=True)
