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
from service.services.simulations.manifests.population_feedback_manifest import (
    InvalidPopulationFeedbackManifest,
    validate_population_feedback_manifest,
    validate_population_feedback_preview,
)


def sample():
    config = {'graph_manifest_sha256': 'a' * 64, 'source_package_sha256': 'b' * 64,
              'source_manifest_sha256': 'c' * 64, 'max_iterations': 5,
              'allow_partial_geometry': True}
    source = {'source_ids': [10, 20], 'simulation': {'duration_ms': 10, 'dt_ms': 1}}
    source_hash = hashlib.sha256(json.dumps(source, sort_keys=True,
                                 separators=(',', ':')).encode()).hexdigest()
    manifest = {'kind': 'experimental-coupled-population', 'configuration_sha256': 'd' * 64,
        'graph_sha256': 'a' * 64,
        'source_package_sha256': 'b' * 64, 'source_manifest_sha256': 'c' * 64,
        'files': [{'name': name, 'bytes': 123, 'sha256': 'e' * 64}
                  for name in ('coupled-population.zip', 'coupled-preview.json',
                               'coupled-delta.bin', 'coupled-events.bin')]}
    preview = {'kind': 'experimental-coupled-population', 'status': 'converged_partial',
        'source_cells': 2, 'source_ids': [10, 20], 'graph_cells': 166700,
        'graph_sha256': 'a' * 64, 'source_configuration_sha256': source_hash,
        'duration_ms': 10, 'network_spikes': 0,
        'unresolved_candidates': 2, 'iterations': 2,
        'interpretation': 'physical recording is limited to source cells; '
                          'the remaining network is uncalibrated LIF',
        'timeline': {'samples': 11, 'shown_samples': 2, 'stimulus_boundaries_preserved': True,
                     'time_ms': [0., 10.], 'neural_uv': [0., 1.], 'total_uv': [0., 2.],
                     'stimulus_fraction': [0., 0.], 'network_spikes_by_ms': [0] * 11,
                     'edge_event_count': 4,
                     'units': {'time_ms': 'ms', 'neural_uv': 'µV', 'total_uv': 'µV'}}}
    return config, manifest, preview


def test_feedback_publication_rejects_inconsistent_results():
    config, manifest, preview = sample()
    source = {'source_ids': [10, 20], 'simulation': {'duration_ms': 10, 'dt_ms': 1}}
    validate_population_feedback_manifest(manifest, configuration_sha256='d' * 64,
                                          configuration=config)
    validate_population_feedback_preview(preview, config, source)
    with pytest.raises(InvalidPopulationFeedbackManifest):
        validate_population_feedback_manifest({**manifest, 'source_package_sha256': 'f' * 64},
                                              configuration_sha256='d' * 64, configuration=config)
    with pytest.raises(InvalidPopulationFeedbackManifest):
        validate_population_feedback_preview(preview, {**config, 'allow_partial_geometry': False},
                                             source)
    with pytest.raises(InvalidPopulationFeedbackManifest):
        validate_population_feedback_preview({**preview, 'source_cells': 166700}, config, source)


def test_feedback_reports_source_geometry_gaps_independently():
    config, _, preview = sample()
    source = {'source_ids': [10, 20], 'allow_partial_geometry': True,
              'simulation': {'duration_ms': 10, 'dt_ms': 1}}
    source_hash = hashlib.sha256(json.dumps(source, sort_keys=True,
                                 separators=(',', ':')).encode()).hexdigest()
    partial = {**preview, 'source_configuration_sha256': source_hash,
               'unresolved_candidates': 0, 'source_unresolved_graph_pairs': 3}
    validate_population_feedback_preview(partial, config, source)
    with pytest.raises(InvalidPopulationFeedbackManifest):
        validate_population_feedback_preview({**partial, 'status': 'converged'}, config, source)
    with pytest.raises(InvalidPopulationFeedbackManifest):
        validate_population_feedback_preview({**partial, 'source_unresolved_graph_pairs': True},
                                             config, source)


def test_refined_feedback_requires_bounded_geometric_summary():
    config, _, preview = sample()
    source = {'source_ids': [10, 20], 'simulation': {'duration_ms': 10, 'dt_ms': 1}}
    config['discretization'] = {'max_shift_um': 2., 'max_observation_distance_um': 2.,
                                'max_nseg': 9}
    geometry = {'checked_events': 5, 'relocated_endpoints': 2, 'max_shift_um': .4,
                'max_observation_distance_um': 1.9}
    with pytest.raises(InvalidPopulationFeedbackManifest, match='feedback_discretization'):
        validate_population_feedback_preview(preview, config, source)
    validate_population_feedback_preview({**preview, 'geometry_discretization': geometry},
                                         config, source)
    bad = {**geometry, 'max_observation_distance_um': 2.1}
    with pytest.raises(InvalidPopulationFeedbackManifest, match='feedback_discretization'):
        validate_population_feedback_preview({**preview, 'geometry_discretization': bad},
                                             config, source)


def test_feedback_manifest_accepts_optional_source_markers_without_losing_required_files():
    config, manifest, _ = sample()
    marker = {'name': 'coupled-source-events.bin', 'bytes': 80, 'sha256': 'f' * 64}
    extended = {**manifest, 'files': [*manifest['files'], marker]}
    validate_population_feedback_manifest(extended, configuration_sha256='d' * 64,
                                          configuration=config)
    with pytest.raises(InvalidPopulationFeedbackManifest):
        validate_population_feedback_manifest(
            {**manifest, 'files': [*manifest['files'][:-1], marker]},
            configuration_sha256='d' * 64, configuration=config)


@pytest.mark.asyncio
async def test_feedback_creation_checks_source_owner_and_package(monkeypatch):
    config, _, _ = sample()
    user_id, source_id = uuid4(), uuid4()
    source = SimpleNamespace(manifest={}, files=[], configuration={'source_ids': [10, 20]})
    @asynccontextmanager
    async def session():
        yield object()
    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session), storage=None)
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    resolver = AsyncMock(return_value=source)
    monkeypatch.setattr(api, 'owned_fragment_source', resolver)
    monkeypatch.setattr(api, 'build_fragment_package', AsyncMock(return_value={
        'sha256': 'b' * 64, 'manifest_sha256': 'c' * 64}))
    digest = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':')).encode())
    response = httpx.Response(200, json={'configuration': config,
        'configuration_sha256': digest.hexdigest()}, request=httpx.Request('POST', 'http://g/test'))
    @asynccontextmanager
    async def generator():
        yield SimpleNamespace(post=AsyncMock(return_value=response))
    monkeypatch.setattr(api, 'generator_client', generator)
    create = AsyncMock(return_value={'id': 'queued'})
    monkeypatch.setattr(api, 'create_checked_run', create)
    owner = SimpleNamespace(user_id=user_id)
    payload = api.RunCreate(request_id=uuid4(), parent_run_id=source_id, configuration=config)
    assert await api.create_population_feedback_run(payload, owner) == {'id': 'queued'}
    assert resolver.await_args.args[1:] == (user_id, source_id, 'a' * 64)
    bad = payload.model_copy(update={
        'configuration': {**config, 'source_package_sha256': 'f' * 64}})
    with pytest.raises(HTTPException) as error:
        await api.create_population_feedback_run(bad, owner)
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_feedback_listing_requires_parent_ownership(monkeypatch):
    source_id, user_id = uuid4(), uuid4()
    queries = []
    class Session:
        async def execute(self, statement):
            queries.append(statement)
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    @asynccontextmanager
    async def session():
        yield Session()
    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session))
    monkeypatch.setattr(api, 'get_current_container', lambda: SimpleNamespace(infra=infra))
    owned = AsyncMock()
    monkeypatch.setattr(api, 'owned', owned)
    assert await api.list_population_feedback_runs(source_id, SimpleNamespace(user_id=user_id)) == {
        'items': []}
    owned.assert_awaited_once()
    assert len(queries) == 1
    denied = AsyncMock(side_effect=HTTPException(404, 'not found'))
    monkeypatch.setattr(api, 'owned', denied)
    with pytest.raises(HTTPException) as error:
        await api.list_population_feedback_runs(source_id, SimpleNamespace(user_id=uuid4()))
    assert error.value.status_code == 404 and len(queries) == 1
