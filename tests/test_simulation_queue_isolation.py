from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.simulations import tasks


@pytest.mark.asyncio
async def test_worker_rejects_run_belonging_to_other_queue(monkeypatch):
    run = SimpleNamespace(state="queued", execution_queue="different")
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: run)),
        commit=AsyncMock(),
    )

    @asynccontextmanager
    async def context():
        yield session

    infra = SimpleNamespace(
        pg_connector=SimpleNamespace(get_session_context=context, close=AsyncMock()),
        redis_client=None,
    )
    monkeypatch.setattr(tasks, "build_infra", lambda _: infra)
    monkeypatch.setattr(tasks, "simulation_queue", lambda: "simulation")
    await tasks.execute(uuid4())
    session.commit.assert_not_awaited()
    infra.pg_connector.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_recovery_scopes_dispatch_and_both_cleanup_queries(monkeypatch):
    queries = []

    async def execute(query):
        queries.append(query)
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []), all=lambda: [])

    session = SimpleNamespace(execute=execute, commit=AsyncMock())

    @asynccontextmanager
    async def context():
        yield session

    @asynccontextmanager
    async def client():
        yield object()

    infra = SimpleNamespace(
        pg_connector=SimpleNamespace(get_session_context=context, close=AsyncMock()),
        redis_client=None,
    )
    monkeypatch.setattr(tasks, "build_infra", lambda _: infra)
    monkeypatch.setattr(tasks, "simulation_queue", lambda: "simulation-test")
    monkeypatch.setattr(tasks, "generator_client", client)
    await tasks.recover()
    assert len(queries) == 3
    for query in queries:
        assert "simulation_run.execution_queue" in str(query)
        assert "simulation-test" in query.compile().params.values()
