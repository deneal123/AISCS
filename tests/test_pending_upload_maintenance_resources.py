"""Maintenance owns every initialized client, including interrupted initialization."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from service.services.files.infrastructure import maintenance


def resources(monkeypatch):
    from service import settings
    from service.composition import storage as storage_factory
    from service.infrastructure.cache import manager as redis_manager
    from service.infrastructure.database import postgresql
    from service.services.files.application import pending_upload_cleanup

    config = SimpleNamespace(
        storage=SimpleNamespace(backend="minio"), redis=SimpleNamespace(enabled=True), pg=object()
    )
    connector = SimpleNamespace(close=AsyncMock())
    manager = SimpleNamespace(close=AsyncMock(), get_client=Mock())
    storage = SimpleNamespace(_client=SimpleNamespace(_http=SimpleNamespace(clear=Mock())))
    monkeypatch.setattr(settings, "Config", Mock(return_value=config))
    monkeypatch.setattr(postgresql, "PgConnector", Mock(return_value=connector))
    monkeypatch.setattr(redis_manager, "RedisManager", Mock(return_value=manager))
    monkeypatch.setattr(storage_factory, "build_file_storage", Mock(return_value=storage))
    monkeypatch.setattr(
        pending_upload_cleanup,
        "cleanup_pending_uploads",
        AsyncMock(return_value={"status": "success"}),
    )
    return connector, manager, storage, storage_factory, redis_manager, pending_upload_cleanup


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["storage_close", "redis_close", "redis_init"])
async def test_cleanup_failure_does_not_skip_remaining_owned_resources(
    monkeypatch, failure, caplog
):
    connector, manager, storage, _factory, redis_module, _cleanup = resources(monkeypatch)
    if failure == "storage_close":
        storage._client._http.clear.side_effect = OSError("PRIVATE_POOL_BODY")
    elif failure == "redis_close":
        manager.close.side_effect = OSError("PRIVATE_REDIS_BODY")
    else:
        monkeypatch.setattr(
            redis_module, "RedisManager", Mock(side_effect=OSError("PRIVATE_INIT_BODY"))
        )
    try:
        result = await maintenance.run_pending_cleanup()
        assert result == {"status": "unavailable"}
    except OSError:
        assert failure == "redis_init"
    connector.close.assert_awaited_once()
    if failure != "redis_init":
        manager.close.assert_awaited_once()
    assert "PRIVATE_" not in caplog.text


@pytest.mark.asyncio
async def test_repeated_cancel_during_storage_init_drains_and_closes_created_handle(monkeypatch):
    connector, manager, storage, factory, _redis, cleanup = resources(monkeypatch)
    started, release, returned = threading.Event(), threading.Event(), threading.Event()

    def create(_config):
        started.set()
        if not release.wait(5):
            raise TimeoutError("fixture initialization not released")
        returned.set()
        return storage

    monkeypatch.setattr(factory, "build_file_storage", create)
    task = asyncio.create_task(maintenance.run_pending_cleanup())
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "unowned storage initializer survived its caller"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert returned.is_set()
        storage._client._http.clear.assert_called_once()
        manager.close.assert_awaited_once()
        connector.close.assert_awaited_once()
        cleanup.cleanup_pending_uploads.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(returned.wait, 2)


@pytest.mark.asyncio
async def test_cancel_during_cleanup_finishes_closing_but_is_not_success(monkeypatch):
    connector, manager, storage, _factory, _redis, _cleanup = resources(monkeypatch)
    closing, release = asyncio.Event(), asyncio.Event()

    async def close():
        closing.set()
        await release.wait()

    manager.close.side_effect = close
    task = asyncio.create_task(maintenance.run_pending_cleanup())
    try:
        await asyncio.wait_for(closing.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        storage._client._http.clear.assert_called_once()
        manager.close.assert_awaited_once()
        connector.close.assert_awaited_once()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
