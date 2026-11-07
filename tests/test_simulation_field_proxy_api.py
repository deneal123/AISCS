import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from service.services.simulations import api


@pytest.mark.asyncio
async def test_direct_proxy_requires_owned_scene_and_preserves_stimulus(monkeypatch):
    graph, scene_id, owner_id = 'a' * 64, uuid4(), uuid4()
    simulation = {'source_um': [0, 0, 0], 'return_um': [20, 0, 0], 'current_na': -300,
                  'conductivity_s_m': .3, 'clearance_um': 1,
                  'coordinate_frame': 'male-cns-v1.0-native-um', 'duration_ms': 2}
    derived = {key: value for key, value in simulation.items() if key != 'duration_ms'}
    derived.update(graph_manifest_sha256=graph, seed=1, gain=2., waveform=[0., 1.],
                   allow_partial_geometry=True, allow_missing_curvature=False,
                   allow_contact_exclusion=False)
    digest = hashlib.sha256(json.dumps(derived, sort_keys=True, separators=(',', ':'),
                                       allow_nan=False).encode()).hexdigest()
    scene = SimpleNamespace(state='completed', result={'preview': {'connectome': {
        'manifest_sha256': graph}}})

    @asynccontextmanager
    async def session_context():
        yield object()

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    lookup = AsyncMock(return_value=scene)
    monkeypatch.setattr(api, 'owned', lookup)
    response = httpx.Response(200, json={'configuration': derived, 'configuration_sha256': digest},
                              request=httpx.Request('POST', 'http://generator/derive'))
    client = SimpleNamespace(post=AsyncMock(return_value=response))

    @asynccontextmanager
    async def generator():
        yield client

    monkeypatch.setattr(api, 'generator_client', generator)
    create = AsyncMock(return_value={'id': 'queued'})
    monkeypatch.setattr(api, 'create_checked_run', create)
    payload = api.FieldProxyFromSimulationRequest(request_id=uuid4(), simulation=simulation,
        graph_manifest_sha256=graph, seed=1, gain=2., allow_partial_geometry=True,
        allow_missing_curvature=False, allow_contact_exclusion=False)
    result = await api.create_field_proxy_direct(scene_id, payload, SimpleNamespace(user_id=owner_id))
    assert result == {'id': 'queued'}
    assert create.await_args.args[0].parent_run_id == scene_id
    assert create.await_args.args[0].configuration == derived
    lookup.assert_awaited_once_with(lookup.await_args.args[0], scene_id, owner_id)
    scene.result['preview']['connectome']['manifest_sha256'] = 'b' * 64
    with pytest.raises(HTTPException) as error:
        await api.create_field_proxy_direct(scene_id, payload, SimpleNamespace(user_id=owner_id))
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_field_proxy_requires_owned_matching_scene_and_validated_payload(monkeypatch):
    graph = 'a' * 64
    scene = SimpleNamespace(state='completed', result={'preview': {'connectome': {
        'manifest_sha256': graph}}})
    session = object()

    @asynccontextmanager
    async def session_context():
        yield session

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    lookup = AsyncMock(return_value=scene)
    monkeypatch.setattr(api, 'owned', lookup)
    config = {'graph_manifest_sha256': graph, 'gain': 1, 'waveform': [0, 1],
              'coordinate_frame': 'male-cns-v1.0-native-um'}
    digest = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':'),
                                       allow_nan=False).encode()).hexdigest()
    response = httpx.Response(200, json={'configuration': config, 'configuration_sha256': digest},
                              request=httpx.Request('POST', 'http://generator/validate'))
    client = SimpleNamespace(post=AsyncMock(return_value=response))

    @asynccontextmanager
    async def generator():
        yield client

    monkeypatch.setattr(api, 'generator_client', generator)
    create = AsyncMock(return_value={'id': 'queued'})
    monkeypatch.setattr(api, 'create_checked_run', create)
    owner = SimpleNamespace(user_id=uuid4())
    payload = api.RunCreate(request_id=uuid4(), parent_run_id=uuid4(), configuration=config)
    assert await api.create_field_proxy_run(payload, owner) == {'id': 'queued'}
    lookup.assert_awaited_once_with(session, payload.parent_run_id, owner.user_id)
    create.assert_awaited_once()
    scene.result['preview']['connectome']['manifest_sha256'] = 'b' * 64
    with pytest.raises(HTTPException) as error:
        await api.create_field_proxy_run(payload, owner)
    assert error.value.status_code == 409
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_derived_proxy_preserves_owned_physical_stimulus(monkeypatch):
    graph, source_id, owner_id = 'a' * 64, uuid4(), uuid4()
    simulation = {'source_um': [0, 0, 0], 'return_um': [20, 0, 0], 'current_na': -300,
                  'conductivity_s_m': .3, 'clearance_um': 1,
                  'coordinate_frame': 'male-cns-v1.0-native-um', 'duration_ms': 2}
    source = SimpleNamespace(configuration={'graph_manifest_sha256': graph, 'seed': 1,
                                             'simulation': simulation})
    derived = {key: value for key, value in simulation.items() if key != 'duration_ms'}
    derived.update(graph_manifest_sha256=graph, seed=1, gain=2., waveform=[0., 1.],
                   allow_partial_geometry=True, allow_missing_curvature=False,
                   allow_contact_exclusion=False)
    digest = hashlib.sha256(json.dumps(derived, sort_keys=True, separators=(',', ':'),
                                       allow_nan=False).encode()).hexdigest()

    @asynccontextmanager
    async def session_context():
        yield object()

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    monkeypatch.setattr(api, 'owned', AsyncMock(return_value=SimpleNamespace(
        configuration={'graph_manifest_sha256': graph})))
    lookup = AsyncMock(return_value=source)
    monkeypatch.setattr(api, 'owned_fragment_source', lookup)
    response = httpx.Response(200, json={'configuration': derived, 'configuration_sha256': digest},
                              request=httpx.Request('POST', 'http://generator/derive'))
    client = SimpleNamespace(post=AsyncMock(return_value=response))

    @asynccontextmanager
    async def generator():
        yield client

    monkeypatch.setattr(api, 'generator_client', generator)
    create = AsyncMock(return_value={'id': 'queued'})
    monkeypatch.setattr(api, 'create_checked_run', create)
    request = api.FieldProxyFromFragmentRequest(request_id=uuid4(), gain=2.,
        allow_partial_geometry=True, allow_missing_curvature=False, allow_contact_exclusion=False)
    result = await api.create_field_proxy_from_fragment(source_id, request,
                                                        SimpleNamespace(user_id=owner_id))
    assert result == {'id': 'queued'}
    assert create.await_args.args[0].parent_run_id == source_id
    assert create.await_args.args[0].configuration == derived
    lookup.assert_awaited_once_with(lookup.await_args.args[0], owner_id, source_id, graph)
    derived['source_um'] = [9, 9, 9]
    tampered = httpx.Response(200, json={'configuration': derived, 'configuration_sha256': digest},
                             request=httpx.Request('POST', 'http://generator/derive'))
    client.post.return_value = tampered
    with pytest.raises(HTTPException) as error:
        await api.create_field_proxy_from_fragment(source_id, request,
                                                   SimpleNamespace(user_id=owner_id))
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_proxy_history_is_limited_to_owned_parent(monkeypatch):
    parent, user = uuid4(), uuid4()
    row = SimpleNamespace(id=uuid4())
    scalar_rows = SimpleNamespace(all=lambda: [row])
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: scalar_rows)))

    @asynccontextmanager
    async def session_context():
        yield session

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    lookup = AsyncMock()
    monkeypatch.setattr(api, 'owned', lookup)
    monkeypatch.setattr(api, 'view', lambda value, **_kwargs: {'id': str(value.id)})
    result = await api.list_field_proxy_runs(parent, SimpleNamespace(user_id=user))
    assert result == {'items': [{'id': str(row.id)}]}
    lookup.assert_awaited_once_with(session, parent, user)
    statement = str(session.execute.await_args.args[0])
    assert 'simulation_run.user_id' in statement and 'simulation_run.parent_run_id' in statement
