"""Хранилище фидбэка по сообщениям (👍/👎) на Redis — без миграции и без правок
воркера. Ключ фидбэка вычисляется из СОДЕРЖИМОГО ответа (FNV-1a по UTF-8), а не из
message_id: у live-сообщений на клиенте нет серверного id, а контент-хеш совпадает
и для только что полученного, и для перечитанного из истории ответа. Реплика хеша
на фронте — frontend/src/features/chat/utils/feedbackKey.js (обязаны совпадать)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_FNV_OFFSET = 0x811C9DC5
_FNV_PRIME = 0x01000193
VALID_RATINGS = {"up", "down"}


def feedback_key(content: str) -> str:
    """FNV-1a (32-bit) по UTF-8-байтам обрезанного контента → 8 hex-символов."""
    data = (content or "").strip().encode("utf-8")
    h = _FNV_OFFSET
    for b in data:
        h ^= b
        h = (h * _FNV_PRIME) & 0xFFFFFFFF
    return format(h, "08x")


def _redis_key(thread_id: str) -> str:
    return f"chat:fb:{thread_id}"


async def set_feedback(redis: Any, thread_id: str, content_key: str, rating: str | None) -> None:
    """rating in {up, down} — записать; иначе (none/пусто) — снять. Best-effort."""
    if redis is None or not content_key:
        return
    try:
        key = _redis_key(thread_id)
        if rating in VALID_RATINGS:
            await redis.hset(key, content_key, rating)
        else:
            await redis.hdel(key, content_key)
    except Exception:
        logger.debug("Failed to store message feedback", exc_info=True)


async def get_feedback_map(redis: Any, thread_id: str) -> dict[str, str]:
    """content_key -> rating для треда (для восстановления при перечитывании)."""
    if redis is None:
        return {}
    try:
        raw = await redis.hgetall(_redis_key(thread_id))
        out: dict[str, str] = {}
        for k, v in (raw or {}).items():
            kk = k.decode() if isinstance(k, bytes) else str(k)
            vv = v.decode() if isinstance(v, bytes) else str(v)
            out[kk] = vv
        return out
    except Exception:
        logger.debug("Failed to read message feedback", exc_info=True)
        return {}
