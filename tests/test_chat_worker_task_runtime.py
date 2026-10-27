"""Ресурсы Celery очищаются в исходном loop, без PostgreSQL и запуска стенда."""

import asyncio
import gc
import logging
import warnings
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.infrastructure.database.postgresql import PgConnector
from service.services.chat.infrastructure.chat_worker.task_runtime import run_coroutine


@pytest.fixture(autouse=True)
def isolated_pool(monkeypatch):
    for name in ("_engine", "_session_maker", "_bound_loop"):
        monkeypatch.setattr(PgConnector, name, None)


@pytest.fixture(autouse=True)
def capture_cleanup_logs(caplog):
    # The production service logger doesn't propagate to pytest's root handler.
    # Capture these two owners directly, independent of main.py import order.
    loggers = [
        logging.getLogger(name)
        for name in (
            "service.infrastructure.database.postgresql",
            "service.services.chat.infrastructure.chat_worker.task_runtime",
        )
    ]
    for logger in loggers:
        logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        for logger in loggers:
            logger.removeHandler(caplog.handler)


def bind_pool(monkeypatch, dispose):
    engine = SimpleNamespace(dispose=dispose)
    monkeypatch.setattr(PgConnector, "_engine", engine)
    monkeypatch.setattr(PgConnector, "_session_maker", object())
    monkeypatch.setattr(PgConnector, "_bound_loop", asyncio.get_running_loop())
    return engine


def test_consecutive_tasks_dispose_on_their_own_live_loop(monkeypatch):
    loops, closed = [], []

    async def run():
        loop = asyncio.get_running_loop()
        loops.append(loop)

        async def dispose():
            assert asyncio.get_running_loop() is loop
            assert not loop.is_closed()
            closed.append(loop)

        bind_pool(monkeypatch, dispose)
        return {"status": "success", "receipt_id": "unchanged"}

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        for _ in range(2):
            assert run_coroutine(run()) == {"status": "success", "receipt_id": "unchanged"}
            assert PgConnector._engine is None
            assert PgConnector._session_maker is None
            assert PgConnector._bound_loop is None
        gc.collect()
    assert len(loops) == 2 and loops[0] is not loops[1]
    assert closed == loops and all(loop.is_closed() for loop in loops)
    assert not [warning for warning in caught if issubclass(warning.category, RuntimeWarning)]


def test_background_session_cleanup_finishes_before_pool_disposal(monkeypatch):
    order = []

    async def run():
        async def background():
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                order.append("session_closed")

        async def dispose():
            assert order == ["session_closed"]
            order.append("pool_disposed")

        bind_pool(monkeypatch, dispose)
        asyncio.create_task(background())
        await asyncio.sleep(0)
        return "completed"

    assert run_coroutine(run()) == "completed"
    assert order == ["session_closed", "pool_disposed"]


def test_async_generator_finally_runs_before_pool_disposal(monkeypatch):
    order, keepalive = [], []

    async def run():
        async def session_generator():
            try:
                yield "session"
            finally:
                await asyncio.sleep(0)
                order.append("generator_closed")

        async def dispose():
            assert order == ["generator_closed"]
            order.append("pool_disposed")

        bind_pool(monkeypatch, dispose)
        generator = session_generator()
        keepalive.append(generator)
        assert await anext(generator) == "session"

    run_coroutine(run())
    assert order == ["generator_closed", "pool_disposed"]


@pytest.mark.parametrize("error", [ValueError("original_failure"), asyncio.CancelledError()])
def test_failure_and_cancellation_still_dispose_without_replacing_error(monkeypatch, error):
    dispose = AsyncMock()

    async def run():
        bind_pool(monkeypatch, dispose)
        raise error

    with pytest.raises(type(error)) as raised:
        run_coroutine(run())
    assert raised.value is error
    dispose.assert_awaited_once()
    assert PgConnector._engine is None


def test_cleanup_failure_is_private_and_does_not_replace_task_result(monkeypatch, caplog):
    dispose = AsyncMock(side_effect=OSError("private-database-diagnostic"))

    async def run():
        bind_pool(monkeypatch, dispose)
        return {"status": "partial", "receipt_id": "original"}

    with caplog.at_level(logging.WARNING):
        assert run_coroutine(run()) == {"status": "partial", "receipt_id": "original"}
    dispose.assert_awaited_once()
    assert "database cleanup failed" in caplog.text
    assert "private-database-diagnostic" not in caplog.text


def test_background_finalizer_failure_is_reported_without_private_details(caplog):
    async def run():
        async def background():
            try:
                await asyncio.Event().wait()
            finally:
                raise OSError("private-background-diagnostic")

        asyncio.create_task(background())
        await asyncio.sleep(0)
        return {"status": "partial", "receipt_id": "original"}

    with caplog.at_level(logging.WARNING):
        assert run_coroutine(run()) == {"status": "partial", "receipt_id": "original"}
    assert "worker background cleanup failed" in caplog.text
    assert "private-background-diagnostic" not in caplog.text


def test_foreign_loop_pool_is_not_closed_by_worker(monkeypatch):
    foreign_loop, dispose = asyncio.new_event_loop(), AsyncMock()

    async def run():
        bind_pool(monkeypatch, dispose)
        monkeypatch.setattr(PgConnector, "_bound_loop", foreign_loop)

    try:
        run_coroutine(run())
        dispose.assert_not_awaited()
    finally:
        foreign_loop.close()


def test_sync_created_unbound_pool_is_closed_in_task_loop(monkeypatch):
    dispose = AsyncMock()
    monkeypatch.setattr(PgConnector, "_engine", SimpleNamespace(dispose=dispose))

    async def run():
        return "maintenance"

    assert run_coroutine(run()) == "maintenance"
    dispose.assert_awaited_once()
    assert PgConnector._engine is None


def test_disposal_cannot_clear_a_replacement_engine(monkeypatch):
    replacement = SimpleNamespace(dispose=AsyncMock())

    async def run():
        async def dispose():
            monkeypatch.setattr(PgConnector, "_engine", replacement)

        bind_pool(monkeypatch, dispose)

    run_coroutine(run())
    assert PgConnector._engine is replacement
    replacement.dispose.assert_not_awaited()


def test_non_coroutine_awaitable_remains_supported():
    class Result:
        def __await__(self):
            async def value():
                return "result"

            return value().__await__()

    assert run_coroutine(Result()) == "result"
