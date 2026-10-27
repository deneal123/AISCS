"""Доставка резюме: неизвестный ACK не является ни успехом, ни допуском повтора."""

import hashlib

from service.infrastructure.cache.manager import call_redis
from service.services.analytics.application.memory.service import MemoryService
from service.shared.memory_outcomes import MemoryWriteResult


async def project_summary(*, client, thread_id: str, user_id: str, summary: str) -> str:
    digest = hashlib.sha256(summary.encode()).hexdigest()
    key = f"gpthub:memos_summary_delivery:{thread_id}:{digest}"
    try:
        # Без TTL: истечение времени не доказывает, что удалённая запись не состоялась.
        owned = await call_redis(client, "set", key, "unknown", nx=True)
        if not owned:
            state = await call_redis(client, "get", key)
            return state.decode() if isinstance(state, bytes) else str(state or "unknown")
    except Exception:
        return "unknown"
    result = await MemoryService().remember_conversation(
        user_id,
        [{"role": "user", "content": f"Резюме предыдущего диалога: {summary}"}],
        metadata={"kind": "summary", "thread_id": thread_id, "delivery_id": digest},
    )
    try:
        if result is MemoryWriteResult.CONFIRMED:
            await call_redis(client, "set", key, "confirmed")
        elif result in (MemoryWriteResult.UNAVAILABLE, MemoryWriteResult.REJECTED):
            await call_redis(client, "delete", key)
    except Exception:
        return "unknown"
    return result.value
