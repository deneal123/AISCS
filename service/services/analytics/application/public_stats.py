"""Публичная агрегированная статистика проекта для hero-страницы (БЕЗ auth).

Отдаёт: пользователей в БД, всего потрачено токенов проектом, посещений сайта.
Кэш 60с (чтобы не бить БД на каждый заход). Visits — Redis-счётчик заходов на hero.
Данные агрегированные и обезличенные — публиковать безопасно.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import text

from service.infrastructure.cache.redis_manager import RedisManager
from service.infrastructure.database.postgresql import PgConnector
from service.settings import config

logger = logging.getLogger(__name__)

_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_TTL_SEC = 60.0
_VISITS_KEY = "public:visits"
_VISIT_DEDUP_TTL = 86400  # окно уникальности визита — сутки


async def _visits(increment: bool, visitor_id: str | None) -> int | None:
    try:
        client = RedisManager(config.redis).get_client()
        if increment and visitor_id:
            # Инкремент ТОЛЬКО для нового посетителя в окне суток. Раньше счётчик рос на
            # КАЖДЫЙ хит /public — F5 в цикле накручивал любое число. Дедуп по хэшу IP
            # (uvicorn --proxy-headers → реальный клиентский IP) делает метрику осмысленной
            # (уникальные визиты) и неинфлируемой. Без visitor_id только читаем.
            marker = f"public:visit:{visitor_id}"
            is_new = await client.set(marker, "1", nx=True, ex=_VISIT_DEDUP_TTL)
            if is_new:
                return int(await client.incr(_VISITS_KEY))
        raw = await client.get(_VISITS_KEY)
        return int(raw) if raw is not None else 0
    except Exception:
        logger.debug("public visits counter unavailable", exc_info=True)
        return None


async def get_public_stats(
    *, increment_visit: bool = True, visitor_id: str | None = None
) -> dict[str, Any]:
    visits = await _visits(increment_visit, visitor_id)

    now = time.time()
    if _CACHE["data"] is not None and (now - _CACHE["ts"]) < _TTL_SEC:
        return {**_CACHE["data"], "visits": visits}

    users = 0
    tokens_spent = 0
    try:
        connector = PgConnector(config.pg)
        async for session in connector.get_session():
            users = int(
                (await session.execute(text('SELECT COUNT(*) FROM profile."user"'))).scalar() or 0
            )
            tokens_spent = int(
                (
                    await session.execute(
                        text(
                            "SELECT COALESCE(SUM(tokens), 0) FROM profile.billing_events "
                            "WHERE event_type = 'usage'"
                        )
                    )
                ).scalar()
                or 0
            )
            break
    except Exception:
        logger.exception("public stats DB query failed")

    data = {"users": users, "tokens_spent": tokens_spent}
    _CACHE["data"] = data
    _CACHE["ts"] = now
    return {**data, "visits": visits}
