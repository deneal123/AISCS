"""Персист «Хода рассуждения» (trace) на Redis — тем же приёмом, что и фидбэк:
ключ = контент-хеш ПОЛЬЗОВАТЕЛЬСКОГО запроса (feedback_key), а не client-id. Так
трейс переживает переоткрытие треда и корректно ре-анкорится к тому же сообщению
без миграции, без правок воркера и без гонок client-id. Пишет сам фронт по
завершении сессии; читает — при загрузке истории."""

from __future__ import annotations

import json
import logging
from typing import Any

from service.services.chat.infrastructure.feedback_store import (
    feedback_key,  # noqa: F401 (reused key)
)

logger = logging.getLogger(__name__)

# Защита от разбухания: очень длинный trace (например, огромные <think>) не пишем.
_MAX_TRACE_BYTES = 200_000


def _redis_key(thread_id: str) -> str:
    return f"chat:trace:{thread_id}"


async def set_trace(redis: Any, thread_id: str, content_key: str, trace: Any) -> None:
    if redis is None or not content_key or trace is None:
        return
    try:
        payload = json.dumps(trace, ensure_ascii=False)
        if len(payload.encode("utf-8")) > _MAX_TRACE_BYTES:
            return
        await redis.hset(_redis_key(thread_id), content_key, payload)
    except Exception:
        logger.debug("Failed to store trace", exc_info=True)


async def get_trace_map(redis: Any, thread_id: str) -> dict[str, Any]:
    if redis is None:
        return {}
    try:
        raw = await redis.hgetall(_redis_key(thread_id))
        out: dict[str, Any] = {}
        for k, v in (raw or {}).items():
            kk = k.decode() if isinstance(k, bytes) else str(k)
            vv = v.decode() if isinstance(v, bytes) else str(v)
            try:
                out[kk] = json.loads(vv)
            except Exception:
                continue
        return out
    except Exception:
        logger.debug("Failed to read traces", exc_info=True)
        return {}
