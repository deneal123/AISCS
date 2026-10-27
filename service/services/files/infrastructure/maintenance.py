"""Scheduled temporary upload retention; only bounded aggregates leave the task."""

import asyncio
import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


async def _join_owned_task(task: asyncio.Task[Any], *, propagate_cancel: bool = False) -> Any:
    """Repeated cancellation must not abandon an initializer or resource cleanup."""
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            interrupted = True
    result = task.result()
    if interrupted and propagate_cancel:
        raise asyncio.CancelledError
    return result


async def _close_resources(storage: Any, manager: Any, connector: Any) -> bool:
    clean = True
    if storage is not None:
        try:
            storage._client._http.clear()
        except Exception:
            clean = False
            logger.warning(
                "pending upload client cleanup unavailable",
                extra={"component": "file_storage", "failure_code": "cleanup"},
            )
    for resource, component in ((manager, "redis_cache"), (connector, "repository")):
        if resource is None:
            continue
        try:
            async with asyncio.timeout(5):
                await resource.close()
        except (Exception, asyncio.CancelledError):
            clean = False
            logger.warning(
                "pending upload client cleanup unavailable",
                extra={"component": component, "failure_code": "cleanup"},
            )
    return clean


async def run_pending_cleanup() -> dict[str, int | str]:
    from service.composition.storage import build_file_storage
    from service.infrastructure.cache.cache import RedisCacheService
    from service.infrastructure.cache.manager import RedisManager
    from service.infrastructure.database.postgresql import PgConnector
    from service.services.files.application.pending_upload_cleanup import cleanup_pending_uploads
    from service.services.files.persistence.file_repository import FileRepository
    from service.settings import Config

    config = Config()
    if config.storage.backend != "minio" or not config.redis.enabled:
        return {"status": "unsupported"}
    connector = manager = storage = None
    try:
        connector = PgConnector(config.pg, force_new=True)
        manager = RedisManager(config.redis)
        initializer = asyncio.create_task(asyncio.to_thread(build_file_storage, config))
        try:
            storage = await asyncio.shield(initializer)
        except asyncio.CancelledError:
            # A cancelled await cannot stop the SDK thread. Take ownership of its
            # returned handle before propagating cancellation, then close it below.
            try:
                storage = await _join_owned_task(initializer)
            except Exception:
                pass
            raise
        result = await cleanup_pending_uploads(
            storage=storage,
            repository=FileRepository(connector),
            cache=RedisCacheService(manager.get_client(), config.redis),
        )
    finally:
        clean = await _join_owned_task(
            asyncio.create_task(_close_resources(storage, manager, connector)),
            propagate_cancel=True,
        )
    if not clean:
        result = {**result, "status": "unavailable"}
    return result


@shared_task(name="service.services.files.infrastructure.maintenance.cleanup_pending_uploads")
def cleanup_pending_uploads_task() -> dict[str, int | str]:
    try:
        return asyncio.run(run_pending_cleanup())
    except Exception:
        logger.warning(
            "pending upload maintenance unavailable",
            extra={"component": "file_storage", "failure_code": "unavailable"},
        )
        return {"status": "unavailable"}
