"""Periodic local-STT settlement using existing reservation maintenance cadence."""

from __future__ import annotations

from typing import Any

from service.infrastructure.cache.manager import RedisManager
from service.services.billing.application.billing_service import BillingService
from service.services.chat.application.video_stt.settlement import reconcile_pending_video_stt
from service.services.jobs.persistence.job_repository import JobRepository


async def settle_video_stt(config: Any, repository: Any, connector: Any) -> dict[str, Any]:
    counts = {"examined": 0, "settled": 0, "deferred": 0, "invalid": 0}
    if not config.redis.enabled:
        return {"status": "unavailable", **counts}
    manager = RedisManager(config.redis)
    try:
        counts = await reconcile_pending_video_stt(
            manager.get_client(),
            BillingService(repository, config.billing),
            JobRepository(connector),
        )
        return {"status": "ready", **counts}
    except Exception:
        return {"status": "unavailable", **counts}
    finally:
        await manager.close()
