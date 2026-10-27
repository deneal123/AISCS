"""Cooperative ownership observation has a single task/cleanup boundary."""

import asyncio
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.execution import (
    watchdog as execution_watchdog,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable


class Session:
    def __init__(self):
        self.observed = 0
        self.invalidated = 0
        self.waiting = asyncio.Event()

    async def scalar(self, _query, _params):
        self.observed += 1
        if self.observed == 1:
            return True
        self.waiting.set()
        await asyncio.Event().wait()

    async def invalidate(self):
        self.invalidated += 1


@pytest.mark.asyncio
async def test_stalled_observation_cancels_and_joins_body(monkeypatch):
    monkeypatch.setattr(execution_watchdog, "_OBSERVATION_INTERVAL_SEC", 0)
    monkeypatch.setattr(execution_watchdog, "_OBSERVATION_TIMEOUT_SEC", 0.01)
    session = Session()
    stopped = asyncio.Event()

    async def body():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    with pytest.raises(JobStateUnavailable):
        async with asyncio.timeout(2):
            await execution_watchdog.run_with_execution_ownership(session, str(uuid4()), body)
    assert session.waiting.is_set() and stopped.is_set()
    assert session.invalidated == 1


@pytest.mark.asyncio
async def test_external_cancellation_joins_observer_and_body(monkeypatch):
    monkeypatch.setattr(execution_watchdog, "_OBSERVATION_INTERVAL_SEC", 0)
    session = Session()
    stopped = asyncio.Event()

    async def body():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    task = asyncio.create_task(
        execution_watchdog.run_with_execution_ownership(session, str(uuid4()), body)
    )
    try:
        async with asyncio.timeout(2):
            await session.waiting.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert stopped.is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancellation_suppressing_body_cannot_report_verified_success(monkeypatch):
    monkeypatch.setattr(execution_watchdog, "_OBSERVATION_INTERVAL_SEC", 0)
    monkeypatch.setattr(execution_watchdog, "_OBSERVATION_TIMEOUT_SEC", 0.01)
    stopped = asyncio.Event()

    async def body():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopped.set()
            return {"status": "success"}

    with pytest.raises(JobStateUnavailable):
        async with asyncio.timeout(2):
            await execution_watchdog.run_with_execution_ownership(Session(), str(uuid4()), body)
    assert stopped.is_set()
