"""Bounded IDE snapshot cleanup; unknown writers are never expired by a timer."""

import asyncio
import logging
from uuid import UUID

from celery import shared_task

logger = logging.getLogger(__name__)
TASK_NAME = "service.services.chat.infrastructure.ide_checkpoint_maintenance.cleanup"


async def run_cleanup() -> dict[str, int | str]:
    from service.composition.storage import build_file_storage
    from service.infrastructure.cache.manager import RedisManager
    from service.infrastructure.database.postgresql import PgConnector
    from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
    from service.services.chat.application.ide.checkpoints.orphans import IdeCheckpointOrphanService
    from service.services.chat.application.ide.checkpoints.retention import (
        IdeCheckpointRetentionService,
    )
    from service.services.chat.persistence.ide.checkpoints.orphans import (
        IdeCheckpointOrphanRepository,
    )
    from service.services.chat.persistence.ide.checkpoints.retention import (
        IdeCheckpointRetentionRepository,
    )
    from service.settings import Config

    config = Config()
    if not config.ide_checkpoints.enabled:
        return {"status": "disabled"}
    if not config.redis.enabled:
        return {"status": "unavailable"}
    if (
        config.storage.backend != "minio"
        and not config.ide_checkpoints.maintenance_local_storage_shared
    ):
        return {"status": "unsupported"}
    connector = manager = None
    storage = None
    try:
        connector = PgConnector(config.pg, force_new=True)
        manager = RedisManager(config.redis)
        # This task has its own event loop; synchronous initialization cannot leave
        # an abandoned SDK initializer running after coroutine cancellation.
        storage = build_file_storage(config)
        checked = IdeCheckpointStorage(storage, max_bytes=config.ide_checkpoints.max_snapshot_bytes)
        redis = manager.get_client()
        key = "ide-checkpoint-cleanup:cursor:" + checked.namespace
        raw = await redis.get(key)
        try:
            cursor = UUID(raw.decode() if isinstance(raw, bytes) else raw) if raw else None
        except (ValueError, TypeError, AttributeError):
            cursor = None
        result = await IdeCheckpointRetentionService(
            IdeCheckpointRetentionRepository(connector), checked
        ).sweep(after_repository_id=cursor)
        # Scheduling hint only, never authority to collect. Advance even when a
        # storage delete failed so one unavailable repository cannot starve others.
        await redis.set(key, str(result.cursor) if result.cursor else "", ex=86400)
        orphan_key = "ide-checkpoint-cleanup:orphans:" + checked.namespace
        raw = await redis.get(orphan_key)
        try:
            parts = (raw.decode() if isinstance(raw, bytes) else raw).split(":") if raw else []
            orphan_cursor = (UUID(parts[0]), UUID(parts[1])) if len(parts) == 2 else None
        except (ValueError, TypeError, AttributeError):
            orphan_cursor = None
        orphans = await IdeCheckpointOrphanService(
            IdeCheckpointOrphanRepository(connector), checked
        ).sweep(after=orphan_cursor)
        await redis.set(
            orphan_key, ":".join(map(str, orphans.cursor)) if orphans.cursor else "", ex=86400
        )
        return {
            "status": "success",
            "repositories": result.repositories,
            "delete_acknowledged": result.delete_acknowledged,
            "pending": result.pending,
            "orphan_snapshots": orphans.examined,
            "orphan_delete_acknowledged": orphans.delete_acknowledged,
            "orphan_pending": orphans.pending,
            "orphan_restore_publications_revoked": orphans.restore_publications_revoked,
        }
    finally:
        try:
            if storage is not None and config.storage.backend == "minio":
                storage._client._http.clear()
        finally:
            try:
                if manager is not None:
                    await manager.close()
            finally:
                if connector is not None:
                    await connector.close()


@shared_task(name=TASK_NAME)
def cleanup() -> dict[str, int | str]:
    try:
        return asyncio.run(run_cleanup())
    except Exception:
        logger.warning(
            "IDE checkpoint cleanup unavailable",
            extra={"component": "ide_checkpoint", "failure_code": "unavailable"},
        )
        return {"status": "unavailable"}
