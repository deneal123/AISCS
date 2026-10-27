"""Hot-path snapshot reads coalesce background work and never publish stale refreshes."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from service.services.admin.application.runtime_settings import RuntimeSettings


@pytest.mark.asyncio
async def test_many_hot_reads_schedule_only_one_pending_refresh(monkeypatch):
    settings = RuntimeSettings()
    settings.bind(Mock())
    gate = asyncio.Event()
    refresh = AsyncMock(side_effect=lambda: gate.wait())

    # AsyncMock does not await an awaitable returned by a synchronous side effect.
    async def pending():
        await gate.wait()

    refresh.side_effect = pending
    monkeypatch.setattr(settings, "refresh", refresh)
    before = set(asyncio.all_tasks())
    try:
        for _ in range(100):
            settings.get_agents("max_subtasks", 3)
        await asyncio.sleep(0)
        assert refresh.await_count == 1
        assert len(set(asyncio.all_tasks()) - before) == 1
    finally:
        gate.set()
        await asyncio.gather(*(set(asyncio.all_tasks()) - before))


@pytest.mark.asyncio
async def test_invalidation_during_refresh_does_not_publish_stale_settings():
    settings = RuntimeSettings()
    entered, release = asyncio.Event(), asyncio.Event()

    async def old_snapshot():
        entered.set()
        await release.wait()
        return {"agents.max_subtasks": 1}

    repository = Mock(get_all=AsyncMock(side_effect=old_snapshot))
    settings.bind(repository)
    settings._cache = {"agents.max_subtasks": 3}
    task = asyncio.create_task(settings.refresh(force=True))
    await entered.wait()
    settings.invalidate()
    release.set()
    await task
    assert settings._cache == {"agents.max_subtasks": 3}
    assert settings._expires_at == 0.0
    repository.get_all.side_effect = None
    repository.get_all.return_value = {"agents.max_subtasks": 5}
    await settings.refresh()
    assert settings.get_agents("max_subtasks", 3) == 5


@pytest.mark.asyncio
async def test_rebind_during_refresh_does_not_publish_old_repository_result():
    settings = RuntimeSettings()
    entered, release = asyncio.Event(), asyncio.Event()

    async def old_snapshot():
        entered.set()
        await release.wait()
        return {"agents.max_subtasks": 1}

    settings.bind(Mock(get_all=AsyncMock(side_effect=old_snapshot)))
    task = asyncio.create_task(settings.refresh(force=True))
    await entered.wait()
    settings.bind(Mock(get_all=AsyncMock(return_value={"agents.max_subtasks": 4})))
    release.set()
    await task
    assert settings._cache == {}
    await settings.refresh()
    assert settings.get_agents("max_subtasks", 3) == 4


@pytest.mark.asyncio
async def test_cancelled_background_refresh_releases_singleflight_for_next_read():
    settings = RuntimeSettings()
    release = asyncio.Event()

    async def snapshot():
        await release.wait()
        return {"agents.max_subtasks": 4}

    repository = Mock(get_all=AsyncMock(side_effect=snapshot))
    settings.bind(repository)
    assert settings.get_agents("max_subtasks", 3) == 3
    task = settings._refresh_task
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert settings._refresh_task is None
    assert settings.get_agents("max_subtasks", 3) == 3
    next_task = settings._refresh_task
    release.set()
    await next_task
    assert repository.get_all.await_count == 2
    assert settings._refresh_task is None
    assert settings.get_agents("max_subtasks", 3) == 4


@pytest.mark.asyncio
async def test_unexpected_background_failure_is_consumed_with_bounded_diagnostic(monkeypatch):
    from service.services.admin.application import runtime_settings as module

    settings = RuntimeSettings()
    settings.bind(Mock())
    monkeypatch.setattr(settings, "refresh", AsyncMock(side_effect=RuntimeError("private-marker")))
    logger = Mock()
    monkeypatch.setattr(module, "logger", logger)
    settings.get_agents("max_subtasks", 3)
    await settings._refresh_task
    assert settings._refresh_task is None
    logger.debug.assert_called_once_with(
        "background settings refresh unavailable",
        extra={"component": "runtime_settings", "failure_code": "unavailable"},
    )
    assert "private-marker" not in repr(logger.mock_calls)


@pytest.mark.asyncio
async def test_stale_failure_cannot_backoff_a_new_binding():
    settings = RuntimeSettings()
    entered, release = asyncio.Event(), asyncio.Event()

    async def failed_snapshot():
        entered.set()
        await release.wait()
        raise RuntimeError("private-marker")

    settings.bind(Mock(get_all=AsyncMock(side_effect=failed_snapshot)))
    task = asyncio.create_task(settings.refresh(force=True))
    await entered.wait()
    settings.bind(Mock(get_all=AsyncMock(return_value={"agents.max_subtasks": 4})))
    release.set()
    await task
    assert settings._expires_at == 0.0
    await settings.refresh()
    assert settings.get_agents("max_subtasks", 3) == 4
