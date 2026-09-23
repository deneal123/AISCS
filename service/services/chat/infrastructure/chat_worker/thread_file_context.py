"""Redis-backed follow-up file context for chat worker turns."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)
THREAD_FILE_TTL_SEC = 7200


async def recall_or_persist_thread_file(
    redis_client, thread_id: str, file_context: str, *, has_new_file: bool = False
) -> str:
    """Persist the last file per thread without reviving stale attachments."""

    if redis_client is None or not thread_id:
        return file_context
    key = f"chat:{thread_id}:last_file"
    try:
        if file_context and file_context.strip():
            await asyncio.to_thread(redis_client.set, key, file_context, ex=THREAD_FILE_TTL_SEC)
            return file_context
        if has_new_file:
            await asyncio.to_thread(redis_client.delete, key)
            return file_context
        prior = await asyncio.to_thread(redis_client.get, key)
        if prior:
            if isinstance(prior, bytes):
                prior = prior.decode("utf-8", "ignore")
            return f"(Ранее приложенный в этом диалоге файл — используй его как контекст.)\n{prior}"
    except Exception:
        logger.debug(
            "thread file recall/persist failed",
            extra={"component": "chat_worker", "failure_code": "persistence"},
        )
    return file_context
