"""Cancel observation survives transient Redis failure and owns child tasks."""

import asyncio

import pytest

from service.services.chat.infrastructure.chat_worker.execution.cancellation import (
    CancelledByUser,
    run_with_cancel,
)


@pytest.mark.asyncio
async def test_transient_poll_failure_does_not_disable_later_cancel(caplog):
    cleaned = asyncio.Event()

    class Redis:
        calls = 0
        deleted = 0

        def get(self, _key):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("PRIVATE_REDIS_BODY")
            return "1"

        def delete(self, _key):
            self.deleted += 1

    async def work():
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    redis = Redis()
    with pytest.raises(CancelledByUser):
        await asyncio.wait_for(
            run_with_cancel(work(), redis_client=redis, celery_task_id="task", poll_interval=0.001),
            timeout=0.2,
        )
    assert cleaned.is_set()
    assert redis.calls >= 2
    assert redis.deleted == 1
    assert "PRIVATE_REDIS_BODY" not in caplog.text


@pytest.mark.asyncio
async def test_outer_cancellation_joins_execution_and_poller(monkeypatch):
    import service.services.chat.infrastructure.chat_worker.execution.cancellation as module

    children = []
    ensure_future = asyncio.ensure_future

    def track(awaitable):
        task = ensure_future(awaitable)
        children.append(task)
        return task

    monkeypatch.setattr(module.asyncio, "ensure_future", track)
    started = asyncio.Event()
    cleaned = asyncio.Event()

    class Redis:
        def get(self, _key):
            return None

    async def work():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    runner = asyncio.create_task(
        run_with_cancel(work(), redis_client=Redis(), celery_task_id="task", poll_interval=0.001)
    )
    try:
        await started.wait()
        runner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner
        assert len(children) == 2
        assert all(task.done() for task in children)
        assert cleaned.is_set()
    finally:
        for task in children:
            task.cancel()
        await asyncio.gather(*children, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("redis_mode", ["expired", "unavailable", "absent"])
async def test_durable_cancel_is_observed_without_live_redis_flag(redis_mode):
    class Redis:
        def get(self, _key):
            if redis_mode == "unavailable":
                raise RuntimeError("PRIVATE_REDIS_BODY")
            return None

        def delete(self, _key):
            return 0

    async def durable_cancel():
        return True

    async def work():
        await asyncio.Event().wait()

    with pytest.raises(CancelledByUser):
        await asyncio.wait_for(
            run_with_cancel(
                work(),
                redis_client=None if redis_mode == "absent" else Redis(),
                celery_task_id="task",
                poll_interval=0.001,
                durable_cancel=durable_cancel,
            ),
            timeout=0.2,
        )


@pytest.mark.asyncio
async def test_durable_observation_outage_does_not_cancel_or_leak_exception(caplog):
    observed = asyncio.Event()

    async def durable_cancel():
        observed.set()
        raise RuntimeError("PRIVATE_SQL_BODY")

    async def work():
        await observed.wait()
        return {"reply": "completed"}

    result = await run_with_cancel(
        work(),
        redis_client=None,
        celery_task_id="task",
        poll_interval=0.001,
        durable_cancel=durable_cancel,
    )
    assert result == {"reply": "completed"}
    assert "PRIVATE_SQL_BODY" not in caplog.text


@pytest.mark.asyncio
async def test_stalled_sql_observation_cannot_block_later_redis_cancel(monkeypatch):
    import service.services.chat.infrastructure.chat_worker.execution.cancellation as module

    monkeypatch.setattr(module, "_CANCEL_OBSERVATION_TIMEOUT_SEC", 0.01, raising=False)
    sql_started = asyncio.Event()
    sql_closed = asyncio.Event()

    class Redis:
        def get(self, _key):
            return "1" if sql_started.is_set() else None

        def delete(self, _key):
            return 1

    async def durable_cancel():
        sql_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            sql_closed.set()

    async def work():
        await asyncio.Event().wait()

    with pytest.raises(CancelledByUser):
        await asyncio.wait_for(
            run_with_cancel(
                work(),
                redis_client=Redis(),
                celery_task_id="task",
                poll_interval=0.001,
                durable_cancel=durable_cancel,
            ),
            timeout=0.2,
        )
    assert sql_closed.is_set()
