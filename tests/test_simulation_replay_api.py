import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from service.services.simulations import api, tasks
from service.services.simulations.inputs.replay_source import ReplaySourceUnavailable


@asynccontextmanager
async def session_context():
    yield object()


@pytest.mark.asyncio
async def test_replay_requires_owned_source_before_validation(monkeypatch):
    source_id, owner_id = uuid4(), uuid4()
    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    lookup = AsyncMock(side_effect=ReplaySourceUnavailable('source_unavailable'))
    monkeypatch.setattr(api, 'owned_replay_source', lookup)
    validate = AsyncMock()
    monkeypatch.setattr(api, 'generator_client', validate)
    payload = api.RunCreate(request_id=uuid4(), configuration={
        'source_run_id': str(source_id), 'graph_manifest_sha256': 'a' * 64,
    })
    with pytest.raises(HTTPException) as error:
        await api.create_replay(payload, SimpleNamespace(user_id=owner_id))
    assert error.value.status_code == 404
    lookup.assert_awaited_once()
    validate.assert_not_called()


@pytest.mark.asyncio
async def test_replay_enqueues_validated_configuration_with_parent(monkeypatch):
    source_id, owner_id = uuid4(), uuid4()
    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    monkeypatch.setattr(api, 'owned_replay_source', AsyncMock(
        return_value=SimpleNamespace(description={'duration_ms': 200.})))
    configuration = {'source_run_id': str(source_id), 'graph_manifest_sha256': 'a' * 64,
                     'simulation': {'duration_ms': 65.}}
    digest = hashlib.sha256(json.dumps(configuration, sort_keys=True,
                                       separators=(',', ':')).encode()).hexdigest()
    checked = {'configuration': configuration, 'configuration_sha256': digest}
    response = httpx.Response(200, json=checked, request=httpx.Request('POST', 'http://g/test'))
    client = SimpleNamespace(post=AsyncMock(return_value=response))

    @asynccontextmanager
    async def client_factory():
        yield client

    monkeypatch.setattr(api, 'generator_client', client_factory)
    create = AsyncMock(return_value={'id': 'queued'})
    monkeypatch.setattr(api, 'create_checked_run', create)
    payload = api.RunCreate(request_id=uuid4(), configuration=configuration)
    assert await api.create_replay(payload, SimpleNamespace(user_id=owner_id)) == {'id': 'queued'}
    assert create.await_args.args[0].parent_run_id == source_id
    assert create.await_args.args[2] == checked
    assert client.post.await_args.args[0] == '/v1/replay-validate'


@pytest.mark.asyncio
async def test_replay_rejects_window_longer_than_source(monkeypatch):
    source_id = uuid4()
    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    monkeypatch.setattr(api, 'owned_replay_source', AsyncMock(
        return_value=SimpleNamespace(description={'duration_ms': 10.})))
    configuration = {'source_run_id': str(source_id), 'graph_manifest_sha256': 'a' * 64,
                     'simulation': {'duration_ms': 11.}}
    digest = hashlib.sha256(json.dumps(configuration, sort_keys=True,
                                       separators=(',', ':')).encode()).hexdigest()
    response = httpx.Response(200, json={'configuration': configuration,
                                        'configuration_sha256': digest},
                              request=httpx.Request('POST', 'http://g/test'))

    @asynccontextmanager
    async def client_factory():
        yield SimpleNamespace(post=AsyncMock(return_value=response))

    monkeypatch.setattr(api, 'generator_client', client_factory)
    create = AsyncMock()
    monkeypatch.setattr(api, 'create_checked_run', create)
    with pytest.raises(HTTPException) as error:
        await api.create_replay(api.RunCreate(request_id=uuid4(), configuration=configuration),
                                SimpleNamespace(user_id=uuid4()))
    assert error.value.status_code == 422
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_rejects_mismatched_validation_response(monkeypatch):
    source_id = uuid4()
    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    monkeypatch.setattr(api, 'owned_replay_source', AsyncMock())
    response = httpx.Response(200, json={'configuration': {'source_run_id': str(uuid4())},
                                        'configuration_sha256': 'a' * 64},
                              request=httpx.Request('POST', 'http://g/test'))

    @asynccontextmanager
    async def client_factory():
        yield SimpleNamespace(post=AsyncMock(return_value=response))

    monkeypatch.setattr(api, 'generator_client', client_factory)
    create = AsyncMock()
    monkeypatch.setattr(api, 'create_checked_run', create)
    payload = api.RunCreate(request_id=uuid4(), configuration={
        'source_run_id': str(source_id), 'graph_manifest_sha256': 'a' * 64,
    })
    with pytest.raises(HTTPException) as error:
        await api.create_replay(payload, SimpleNamespace(user_id=uuid4()))
    assert error.value.status_code == 503
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_rejects_changed_parameters_even_with_matching_digest(monkeypatch):
    source_id = uuid4()
    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    monkeypatch.setattr(api, 'owned_replay_source', AsyncMock())
    configuration = {'source_run_id': str(source_id), 'graph_manifest_sha256': 'a' * 64,
                     'body_id': 99}
    digest = hashlib.sha256(json.dumps(configuration, sort_keys=True,
                                       separators=(',', ':')).encode()).hexdigest()
    response = httpx.Response(200, json={'configuration': configuration,
                                        'configuration_sha256': digest},
                              request=httpx.Request('POST', 'http://g/test'))

    @asynccontextmanager
    async def client_factory():
        yield SimpleNamespace(post=AsyncMock(return_value=response))

    monkeypatch.setattr(api, 'generator_client', client_factory)
    payload = api.RunCreate(request_id=uuid4(), configuration={**configuration, 'body_id': 42})
    with pytest.raises(HTTPException) as error:
        await api.create_replay(payload, SimpleNamespace(user_id=uuid4()))
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_staged_cleanup_uses_owned_checksum(monkeypatch):
    source_id, attempt, owner = uuid4(), uuid4(), uuid4()
    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    monkeypatch.setattr(tasks, 'owned_replay_source', AsyncMock(
        return_value=SimpleNamespace(sha256='b' * 64)))
    response = httpx.Response(200, request=httpx.Request('DELETE', 'http://g/test'))
    client = SimpleNamespace(delete=AsyncMock(return_value=response))
    await tasks.discard_staged_replay(infra, client, attempt, owner, {
        'source_run_id': str(source_id), 'graph_manifest_sha256': 'a' * 64,
    })
    assert client.delete.await_args.args[0].endswith(str(attempt))
    assert client.delete.await_args.kwargs['headers']['X-Content-SHA256'] == 'b' * 64


@pytest.mark.asyncio
async def test_regular_history_excludes_replay_configurations(monkeypatch):
    statements = []

    class Session:
        async def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    @asynccontextmanager
    async def context():
        yield Session()

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    owner = SimpleNamespace(user_id=uuid4())
    await api.list_runs(owner)
    assert 'simulation_run.user_id' in str(statements[-1])
    assert 'source_run_id' in str(statements[-1].compile().params.values())
    await api.list_runs(owner, include_replays=True)
    assert 'simulation_run.user_id' in str(statements[-1])
    assert 'source_run_id' not in str(statements[-1].compile().params.values())


@pytest.mark.asyncio
async def test_replay_listing_checks_parent_and_filters_owner(monkeypatch):
    statements = []

    class Session:
        async def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    @asynccontextmanager
    async def context():
        yield Session()

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    own = AsyncMock()
    monkeypatch.setattr(api, 'owned', own)
    run_id, user_id = uuid4(), uuid4()
    assert await api.list_replays(run_id, SimpleNamespace(user_id=user_id)) == {
        'items': [], 'next_offset': None,
    }
    own.assert_awaited_once_with(own.await_args.args[0], run_id, user_id)
    query = str(statements[0])
    assert 'simulation_run.user_id' in query and 'simulation_run.parent_run_id' in query
    assert 'source_run_id' in str(statements[0].compile().params.values())
