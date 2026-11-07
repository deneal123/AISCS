import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from service.services.simulations import api


@pytest.mark.asyncio
async def test_target_creation_binds_owned_source_package_and_validation(monkeypatch):
    source_id, user_id = uuid4(), uuid4()
    requested = {'graph_manifest_sha256': 'a' * 64, 'source_ids': [10], 'target_id': 20,
                 'duration_ms': 10, 'source_package_sha256': 'b' * 64,
                 'source_manifest_sha256': 'c' * 64}
    source = SimpleNamespace(configuration={'source_ids': [10, 11],
        'simulation': {'duration_ms': 10}}, manifest={}, files=[])
    receipt = {'sha256': 'b' * 64, 'manifest_sha256': 'c' * 64}
    @asynccontextmanager
    async def session():
        yield object()
    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session), storage=None)
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    resolver = AsyncMock(return_value=source)
    monkeypatch.setattr(api, 'owned_fragment_source', resolver)
    monkeypatch.setattr(api, 'build_fragment_package', AsyncMock(return_value=receipt))
    digest = hashlib.sha256(json.dumps(requested, sort_keys=True, separators=(',', ':')).encode())
    response = httpx.Response(200, json={'configuration': requested,
        'configuration_sha256': digest.hexdigest()}, request=httpx.Request('POST', 'http://g/test'))
    @asynccontextmanager
    async def generator():
        yield SimpleNamespace(post=AsyncMock(return_value=response))
    monkeypatch.setattr(api, 'generator_client', generator)
    create = AsyncMock(return_value={'id': 'queued'})
    monkeypatch.setattr(api, 'create_checked_run', create)
    owner = SimpleNamespace(user_id=user_id)
    payload = api.RunCreate(request_id=uuid4(), parent_run_id=source_id, configuration=requested)
    assert await api.create_population_target_run(payload, owner) == {'id': 'queued'}
    assert resolver.await_count == 1
    assert resolver.await_args.args[1:] == (user_id, source_id, 'a' * 64)
    create.assert_awaited_once()
    for changed in ({'source_ids': [12]}, {'target_id': 11}, {'source_package_sha256': 'd' * 64},
                    {'duration_ms': 11}):
        bad = payload.model_copy(update={'configuration': {**requested, **changed}})
        with pytest.raises(HTTPException) as error:
            await api.create_population_target_run(bad, owner)
        assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_target_listing_checks_owner_and_scopes_parent_and_target(monkeypatch):
    source_id, user_id = uuid4(), uuid4()
    queries = []
    class Session:
        async def execute(self, query):
            queries.append(query)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    @asynccontextmanager
    async def session():
        yield Session()
    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    owned = AsyncMock()
    monkeypatch.setattr(api, 'owned', owned)
    result = await api.list_population_target_runs(source_id, 20, SimpleNamespace(user_id=user_id))
    assert result == {'items': []}
    owned.assert_awaited_once()
    assert owned.await_args.args[1:] == (source_id, user_id)
    compiled = queries[0].compile(dialect=postgresql.dialect())
    statement = str(compiled)
    assert 'simulation_run.user_id' in statement
    assert 'simulation_run.parent_run_id' in statement
    assert 'source_package_sha256' in compiled.params.values()
    assert 'target_id' in compiled.params.values()
    assert str(20) in compiled.params.values()
    owned.side_effect = HTTPException(404)
    with pytest.raises(HTTPException) as exc:
        await api.list_population_target_runs(source_id, 20, SimpleNamespace(user_id=uuid4()))
    assert exc.value.status_code == 404
    assert len(queries) == 1
    with pytest.raises(HTTPException) as exc:
        await api.list_population_target_runs(source_id, 0, SimpleNamespace(user_id=user_id))
    assert exc.value.status_code == 422
