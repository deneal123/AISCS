"""Thread-scoped repository references shared by sync and asyncio Redis clients."""

import logging

from service.infrastructure.cache.manager import call_redis

logger = logging.getLogger(__name__)


async def read_thread_repo_graphs(redis_client, thread_id: str | None) -> list[str]:
    """Read newest-first repository graphs, never account-wide document graphs.

    Upload uses LPUSH/LTRIM. Missing Redis/thread and transport failure retain
    the existing best-effort empty result; cancellation remains cancellation.
    """
    if redis_client is None or not thread_id:
        return []
    try:
        raw = await call_redis(redis_client, "lrange", f"chat:{thread_id}:repo_graphs", 0, -1)
    except Exception:
        logger.debug(
            "repository references unavailable",
            extra={"component": "attachment_context", "failure_code": "unavailable"},
        )
        return []
    return [
        item.decode("utf-8", "ignore") if isinstance(item, bytes) else str(item)
        for item in raw or []
    ]
