from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from service.services.chat.application.ide.checkpoints.orphans import OrphanSweepResult
from service.services.chat.application.ide.checkpoints.retention import SweepResult
from service.services.chat.infrastructure import ide_checkpoint_maintenance as maintenance


@pytest.fixture
def dependencies(monkeypatch):
    from service import settings
    from service.composition import storage as storage_module
    from service.infrastructure.cache import manager as redis_manager
    from service.infrastructure.database import postgresql
    from service.services.chat.application.ide.checkpoints import orphans as ide_checkpoint_orphans
    from service.services.chat.application.ide.checkpoints import (
        retention as ide_checkpoint_retention,
    )

    config = SimpleNamespace(
        ide_checkpoints=SimpleNamespace(
            enabled=True, max_snapshot_bytes=1000, maintenance_local_storage_shared=True
        ),
        redis=SimpleNamespace(enabled=True),
        pg=object(),
        storage=SimpleNamespace(backend="local"),
    )
    connector = SimpleNamespace(close=AsyncMock())
    redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock())
    manager = SimpleNamespace(get_client=lambda: redis, close=AsyncMock())
    storage = SimpleNamespace(namespace_id="a" * 64)
    builder = MagicMock(return_value=storage)
    service = SimpleNamespace(sweep=AsyncMock(return_value=SweepResult(0, 0, 0, None)))
    service.orphan_sweep = AsyncMock(return_value=OrphanSweepResult(0, 0, 0, None))
    monkeypatch.setattr(settings, "Config", lambda: config)
    monkeypatch.setattr(postgresql, "PgConnector", lambda *a, **k: connector)
    monkeypatch.setattr(redis_manager, "RedisManager", lambda *_: manager)
    monkeypatch.setattr(storage_module, "build_file_storage", builder)
    monkeypatch.setattr(
        ide_checkpoint_retention, "IdeCheckpointRetentionService", lambda *_: service
    )
    monkeypatch.setattr(
        ide_checkpoint_orphans,
        "IdeCheckpointOrphanService",
        lambda *_: SimpleNamespace(sweep=service.orphan_sweep),
    )
    return config, connector, redis, manager, builder, service


@pytest.mark.asyncio
async def test_disabled_feature_has_no_storage_database_or_cursor_effects(dependencies):
    config, connector, redis, manager, builder, service = dependencies
    config.ide_checkpoints.enabled = False
    assert await maintenance.run_cleanup() == {"status": "disabled"}
    builder.assert_not_called()
    redis.get.assert_not_awaited()
    service.sweep.assert_not_awaited()
    connector.close.assert_not_awaited()
    manager.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_local_directory_cannot_acknowledge_another_containers_object(dependencies):
    config, connector, redis, manager, builder, service = dependencies
    config.ide_checkpoints.maintenance_local_storage_shared = False
    assert await maintenance.run_cleanup() == {"status": "unsupported"}
    builder.assert_not_called()
    redis.get.assert_not_awaited()
    service.sweep.assert_not_awaited()
    connector.close.assert_not_awaited()
    manager.close.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, b"invalid", b""])
async def test_missing_or_invalid_cursor_starts_read_only_discovery(dependencies, value):
    _, connector, redis, manager, _, service = dependencies
    redis.get.return_value = value
    result = await maintenance.run_cleanup()
    assert result == {
        "status": "success",
        "repositories": 0,
        "delete_acknowledged": 0,
        "pending": 0,
        "orphan_snapshots": 0,
        "orphan_delete_acknowledged": 0,
        "orphan_pending": 0,
        "orphan_restore_publications_revoked": 0,
    }
    service.sweep.assert_awaited_once_with(after_repository_id=None)
    redis.set.assert_any_await("ide-checkpoint-cleanup:cursor:" + "a" * 64, "", ex=86400)
    redis.set.assert_any_await("ide-checkpoint-cleanup:orphans:" + "a" * 64, "", ex=86400)
    service.orphan_sweep.assert_awaited_once_with(after=None)
    connector.close.assert_awaited_once()
    manager.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cursor_advances_even_when_some_deletes_remain_pending(dependencies):
    _, connector, redis, manager, _, service = dependencies
    before, after = uuid4(), uuid4()
    redis.get.return_value = str(before).encode()
    service.sweep.return_value = SweepResult(32, 3, 2, after)
    result = await maintenance.run_cleanup()
    service.sweep.assert_awaited_once_with(after_repository_id=before)
    assert result == {
        "status": "success",
        "repositories": 32,
        "delete_acknowledged": 3,
        "pending": 2,
        "orphan_snapshots": 0,
        "orphan_delete_acknowledged": 0,
        "orphan_pending": 0,
        "orphan_restore_publications_revoked": 0,
    }
    assert str(after) not in str(result)
    redis.set.assert_any_await("ide-checkpoint-cleanup:cursor:" + "a" * 64, str(after), ex=86400)
    connector.close.assert_awaited_once()
    manager.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_sweep_does_not_advance_cursor_and_closes_resources(dependencies):
    _, connector, redis, manager, _, service = dependencies
    service.sweep.side_effect = RuntimeError("private storage details")
    with pytest.raises(RuntimeError):
        await maintenance.run_cleanup()
    redis.set.assert_not_awaited()
    connector.close.assert_awaited_once()
    manager.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_orphan_cursor_is_independent_and_output_contains_only_aggregate_counts(dependencies):
    _, connector, redis, manager, _, service = dependencies
    before = (uuid4(), uuid4())
    after = (uuid4(), uuid4())
    redis.get.side_effect = [None, ":".join(map(str, before)).encode()]
    service.orphan_sweep.return_value = OrphanSweepResult(32, 4, 2, after)
    result = await maintenance.run_cleanup()
    service.sweep.assert_awaited_once_with(after_repository_id=None)
    service.orphan_sweep.assert_awaited_once_with(after=before)
    assert result["orphan_snapshots"] == 32
    assert result["orphan_delete_acknowledged"] == 4
    assert result["orphan_pending"] == 2
    assert str(after[0]) not in str(result)
    redis.set.assert_any_await(
        "ide-checkpoint-cleanup:orphans:" + "a" * 64, ":".join(map(str, after)), ex=86400
    )
    connector.close.assert_awaited_once()
    manager.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_orphan_retirement_ack_does_not_advance_orphan_cursor(dependencies):
    _, connector, redis, manager, _, service = dependencies
    service.orphan_sweep.side_effect = RuntimeError("PRIVATE")
    with pytest.raises(RuntimeError):
        await maintenance.run_cleanup()
    assert redis.set.await_count == 1
    assert "orphans:" not in redis.set.await_args.args[0]
    connector.close.assert_awaited_once()
    manager.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_minio_uses_the_remote_namespace_and_closes_the_sdk_pool(dependencies):
    config, _, _, _, builder, _ = dependencies
    config.storage.backend = "minio"
    config.ide_checkpoints.maintenance_local_storage_shared = False
    clear = MagicMock()
    builder.return_value._client = SimpleNamespace(_http=SimpleNamespace(clear=clear))
    assert (await maintenance.run_cleanup())["status"] == "success"
    clear.assert_called_once()


@pytest.mark.asyncio
async def test_failed_storage_initialization_closes_owned_dependencies(dependencies):
    _, connector, redis, manager, builder, service = dependencies
    builder.side_effect = RuntimeError("private configuration")
    with pytest.raises(RuntimeError):
        await maintenance.run_cleanup()
    redis.get.assert_not_awaited()
    service.sweep.assert_not_awaited()
    connector.close.assert_awaited_once()
    manager.close.assert_awaited_once()


def test_task_reports_only_safe_failure_code(monkeypatch, caplog):
    monkeypatch.setattr(
        maintenance, "run_cleanup", AsyncMock(side_effect=RuntimeError("private-key"))
    )
    assert maintenance.cleanup() == {"status": "unavailable"}
    assert "private-key" not in caplog.text


def test_task_is_routed_and_scheduled_on_existing_maintenance_queue():
    from service.infrastructure.messaging.celery_app import celery_app

    assert maintenance.__name__ in celery_app.conf.include
    assert celery_app.conf.task_routes[maintenance.TASK_NAME]["queue"] == "maintenance"
    assert celery_app.conf.beat_schedule["cleanup-ide-checkpoints"] == {
        "task": maintenance.TASK_NAME,
        "schedule": 300.0,
    }
