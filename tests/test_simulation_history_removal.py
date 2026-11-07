from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from service.services.simulations import api


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['completed', 'failed', 'cancelled', 'running'])
async def test_history_removal_is_owned_and_only_allows_terminal_runs(monkeypatch, state):
    run = SimpleNamespace(state=state, hidden_from_history=False)
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def session_context():
        yield session

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    lookup = AsyncMock(return_value=run)
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    monkeypatch.setattr(api, 'owned', lookup)
    run_id, owner_id = uuid4(), uuid4()
    if state == 'running':
        with pytest.raises(HTTPException) as error:
            await api.remove_run_from_history(run_id, SimpleNamespace(user_id=owner_id))
        assert error.value.status_code == 409
        session.commit.assert_not_awaited()
        assert not run.hidden_from_history
    else:
        response = await api.remove_run_from_history(run_id, SimpleNamespace(user_id=owner_id))
        assert response.status_code == 204
        assert run.hidden_from_history
        session.commit.assert_awaited_once()
    lookup.assert_awaited_once_with(session, run_id, owner_id, lock=True)


@pytest.mark.asyncio
async def test_history_removal_rejects_an_unowned_run(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def session_context():
        yield session

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    monkeypatch.setattr(api, 'owned', AsyncMock(side_effect=HTTPException(404, 'not found')))
    with pytest.raises(HTTPException) as error:
        await api.remove_run_from_history(uuid4(), SimpleNamespace(user_id=uuid4()))
    assert error.value.status_code == 404
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_scene_template_is_scoped_to_owner_and_can_use_hidden_scene(monkeypatch):
    scene = SimpleNamespace(id=uuid4())
    result = SimpleNamespace(scalar_one_or_none=lambda: scene)
    session = SimpleNamespace(execute=AsyncMock(return_value=result))

    @asynccontextmanager
    async def session_context():
        yield session

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    monkeypatch.setattr(api, 'view', lambda row: {'id': str(row.id)})
    response = await api.scene_template(SimpleNamespace(user_id=uuid4()))
    assert response == {'id': str(scene.id)}
    statement = str(session.execute.await_args.args[0])
    assert 'simulation_run.user_id' in statement
    assert 'hidden_from_history' not in statement.split('WHERE', 1)[-1]
