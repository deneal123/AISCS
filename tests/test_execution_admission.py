"""Duplicate delivery is nonterminal and cannot enter expensive worker execution."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.execution import run as run_execution
from service.services.chat.infrastructure.chat_worker.run_contracts import WorkerRunRequest


@pytest.mark.asyncio
async def test_two_deliveries_enter_owned_worker_only_once(monkeypatch):
    held = set()
    calls = 0
    entered = asyncio.Event()
    finish = asyncio.Event()

    class Session:
        async def scalar(self, query, params):
            if "pg_locks" in str(query):
                return True
            key = params["key"]
            if "pg_try_advisory_lock" in str(query):
                if key in held:
                    return False
                held.add(key)
                return True
            held.remove(key)
            return True

    @asynccontextmanager
    async def session():
        yield Session()

    async def owned(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await finish.wait()
        return {"status": "success"}

    monkeypatch.setattr(run_execution, "_execute_owned_job", owned)
    request = WorkerRunRequest(str(uuid4()), "synthetic", "synthetic", str(uuid4()))
    kwargs = {
        "hooks": object(),
        "agent_execution": object(),
        "dependency_factory": SimpleNamespace(
            create_pg_connector=lambda _cfg: SimpleNamespace(get_session_context=session)
        ),
    }
    first = asyncio.create_task(run_execution.execute_chat_job(request, **kwargs))
    try:
        await entered.wait()
        second = await run_execution.execute_chat_job(request, **kwargs)
        assert second == {"status": "processing", "job_id": request.job_id}
        assert calls == 1
        finish.set()
        assert await first == {"status": "success"}
        assert held == set()
    finally:
        finish.set()
        await first


@pytest.mark.asyncio
@pytest.mark.parametrize("observation", [False, None, RuntimeError("PRIVATE_LOCK_BODY")])
async def test_lost_execution_lock_cancels_owned_body_without_success(monkeypatch, observation):
    from service.services.chat.infrastructure.chat_worker.execution import (
        watchdog as execution_watchdog,
    )

    started = asyncio.Event()
    stopped = asyncio.Event()
    lost = asyncio.Event()
    observations = 0
    invalidated = 0

    class Session:
        async def scalar(self, query, _params):
            nonlocal observations
            if "pg_locks" not in str(query):
                return True
            observations += 1
            if observations == 1:
                return True
            await started.wait()
            lost.set()
            if isinstance(observation, Exception):
                raise observation
            return observation

        async def invalidate(self):
            nonlocal invalidated
            invalidated += 1

    @asynccontextmanager
    async def session():
        yield Session()

    async def owned(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(execution_watchdog, "_OBSERVATION_INTERVAL_SEC", 0)
    monkeypatch.setattr(run_execution, "_execute_owned_job", owned)
    request = WorkerRunRequest(str(uuid4()), "synthetic", "synthetic", str(uuid4()))
    async with asyncio.timeout(2):
        result = await run_execution.execute_chat_job(
            request,
            hooks=object(),
            agent_execution=object(),
            dependency_factory=SimpleNamespace(
                create_pg_connector=lambda _cfg: SimpleNamespace(get_session_context=session)
            ),
        )
    assert lost.is_set() and stopped.is_set()
    assert result["status"] == "error"
    assert invalidated >= 1
    assert "PRIVATE_LOCK_BODY" not in str(result)


@pytest.mark.asyncio
async def test_unproven_execution_lock_never_starts_owned_body(monkeypatch):
    calls = 0

    class Session:
        async def scalar(self, query, _params):
            return False if "pg_locks" in str(query) else True

        async def invalidate(self):
            pass

    @asynccontextmanager
    async def session():
        yield Session()

    async def owned(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {"status": "success"}

    monkeypatch.setattr(run_execution, "_execute_owned_job", owned)
    request = WorkerRunRequest(str(uuid4()), "synthetic", "synthetic", str(uuid4()))
    result = await run_execution.execute_chat_job(
        request,
        hooks=object(),
        agent_execution=object(),
        dependency_factory=SimpleNamespace(
            create_pg_connector=lambda _cfg: SimpleNamespace(get_session_context=session)
        ),
    )
    assert result["status"] == "error"
    assert calls == 0
