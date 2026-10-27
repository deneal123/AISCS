"""Background recovery yields, respects shutdown, and never logs private bodies."""

import asyncio
import logging

import pytest

from service.utils import background_task_manager as module


@pytest.mark.asyncio
async def test_repeated_registration_reuses_live_loop():
    manager = module.BackgroundTaskManager()
    await manager.start()
    calls = 0
    entered = asyncio.Event()

    async def operation():
        nonlocal calls
        calls += 1
        entered.set()
        await asyncio.Event().wait()

    try:
        first = await manager.start_task_with_restart(operation, "file-scan-loop")
        second = await manager.start_task_with_restart(operation, "file-scan-loop")
        await asyncio.wait_for(entered.wait(), 1)
        assert second is first
        assert len(manager.tasks) == 1
        assert calls == 1
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_finished_registration_can_be_replaced_without_retaining_dead_tasks():
    manager = module.BackgroundTaskManager()
    await manager.start()

    async def cancelled():
        raise asyncio.CancelledError

    first = await manager.start_task_with_restart(cancelled, "file-scan-loop")
    await first
    try:
        replacement = await manager.start_task_with_restart(cancelled, "file-scan-loop")
        assert replacement is not first
        assert manager.tasks == [replacement]
        await replacement
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_distinct_names_remain_independent_and_restart_after_stop():
    manager = module.BackgroundTaskManager()
    await manager.start()

    async def operation():
        await asyncio.Event().wait()

    first = await manager.start_task_with_restart(operation, "file-scan-loop")
    second = await manager.start_task_with_restart(operation, "new-jobs-processor")
    assert first is not second
    assert manager.tasks == [first, second]
    await manager.stop()
    assert first.done() and second.done()
    await manager.start()
    try:
        replacement = await manager.start_task_with_restart(operation, "file-scan-loop")
        assert replacement is not first
        assert manager.tasks == [replacement]
    finally:
        await manager.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_restart_follows_delay_and_shutdown_cancels_active_attempt(monkeypatch, failed):
    manager = module.BackgroundTaskManager()
    await manager.start()
    calls = 0
    waiting, release, restarted, cancelled = (asyncio.Event() for _ in range(4))

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            if failed:
                raise RuntimeError("private-restart-body")
            return
        restarted.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def delay(seconds):
        assert seconds == 5
        waiting.set()
        await release.wait()

    monkeypatch.setattr(module.asyncio, "sleep", delay)
    await manager.start_task_with_restart(operation, "new-jobs-processor")
    try:
        await asyncio.wait_for(waiting.wait(), 1)
        assert calls == 1
        release.set()
        await asyncio.wait_for(restarted.wait(), 1)
        assert calls == 2
    finally:
        await manager.stop()
    assert cancelled.is_set()
    assert not manager.tasks


@pytest.mark.asyncio
async def test_returning_loop_does_not_spin_and_can_be_stopped(monkeypatch):
    manager = module.BackgroundTaskManager()
    await manager.start()
    calls = 0
    sleeping = asyncio.Event()

    async def returned():
        nonlocal calls
        calls += 1
        # Bound the pre-fix busy loop so the regression cannot hang the test runner.
        if calls == 5:
            manager.running = False

    async def delay(seconds):
        assert seconds == 5
        sleeping.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(module.asyncio, "sleep", delay)
    task = await manager.start_task_with_restart(returned, "file-scan-loop")
    # The pre-fix loop runs to its fifth return without yielding.
    observer = asyncio.create_task(sleeping.wait())
    await asyncio.wait({task, observer}, timeout=0.05, return_when=asyncio.FIRST_COMPLETED)
    try:
        assert calls == 1
        assert sleeping.is_set()
    finally:
        await manager.stop()
        observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)
    assert not manager.tasks


@pytest.mark.asyncio
async def test_failure_diagnostics_have_no_exception_body_or_dynamic_task_name(monkeypatch):
    manager = module.BackgroundTaskManager()
    await manager.start()
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    monkeypatch.setattr(module.logger, "handlers", [Capture()])
    monkeypatch.setattr(module.logger, "propagate", False)
    monkeypatch.setattr(module.logger, "level", logging.INFO)

    async def failed():
        manager.running = False
        raise RuntimeError("private-background-body")

    task = await manager.start_task_with_restart(failed, "private-dynamic-name")
    await task
    await manager.stop()
    assert records
    for record in records:
        assert record.exc_info is None
        assert "private-background-body" not in str(record.__dict__)
        assert "private-dynamic-name" not in record.getMessage()
    failure = [record for record in records if record.levelno >= logging.WARNING]
    assert len(failure) == 1
    assert failure[0].component == "background_task"
    assert failure[0].failure_code == "unavailable"
