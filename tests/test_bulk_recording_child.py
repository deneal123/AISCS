import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from service.domain.contracts.population.bulk_recording import (
    BulkRecordingConfig,
    BulkRecordingExecutionRequest,
)
from service.infrastructure.execution.process import Executions, run_bulk_recording_child
from service.presentation.http import build_app
from tests.test_fragment_population_contract import example
from tests.test_replay_execution import FakeProcess


def test_child_publishes_only_verified_result(tmp_path, monkeypatch):
    monkeypatch.setenv('GENERATOR_GPU_REROOT', '1')
    monkeypatch.setenv('GENERATOR_GPU_CELL_MAJOR_BLOCK_THREADS', '128')
    monkeypatch.setenv('GENERATOR_GPU_BLOCK_CELL_SEGMENTS', '10000')
    monkeypatch.setenv('GENERATOR_GPU_CELL_WARPS', '4')
    config = BulkRecordingConfig(graph_manifest_sha256='a' * 64,
                                 simulation=example()['simulation'])
    payload = {'execution_id': str(uuid4()), 'config': config.model_dump(mode='json')}
    graph = SimpleNamespace(provenance={'manifest_sha256': 'a' * 64})
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: graph)
    monkeypatch.setattr('service.infrastructure.execution.process._field_geometry_cache',
                        lambda *_: {'trusted': True})

    def execute(_graph, _simulation, *, output_path, progress, **_kwargs):
        assert _kwargs['solver_options']['reroot'] is True
        assert _kwargs['solver_options']['cell_major_block_threads'] == 128
        assert _kwargs['solver_options']['block_cell_segments'] == 10000
        assert _kwargs['solver_options']['cell_warps'] == 4
        output_path.write_bytes(b'example')
        progress('independent_cells', 1, 1)
        return {'artifact': {'sha256': 'b' * 64}, 'configuration_sha256': config.digest(),
                'geometry_cache_manifest_sha256': 'c' * 64, 'source_index_sha256': 'd' * 64,
                'preview': {'kind': 'experimental-independent-population'}}

    monkeypatch.setattr('service.application.population.bulk_experiment.execute_bulk_experiment',
                        execute)
    monkeypatch.setattr('service.application.population.bulk_recording_export.read_bulk_recording',
                        lambda *_args, **_kwargs: {})
    output = tmp_path / 'output'
    run_bulk_recording_child(payload, str(output))
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf8'))
    assert manifest['kind'] == 'experimental-independent-population'
    assert 'no network feedback' in manifest['interpretation']
    assert manifest['geometry_repair_policy'] == 'disabled'
    assert manifest['source_index_sha256'] == 'd' * 64
    assert manifest['batch_settings']['max_cells'] == 20
    assert manifest['batch_settings']['reroot'] is True
    assert manifest['batch_settings']['cell_major_block_threads'] == 128
    assert manifest['batch_settings']['block_cell_segments'] == 10000
    assert manifest['batch_settings']['cell_warps'] == 4
    assert json.loads((tmp_path / 'progress.json').read_text())['done'] == 1


def test_child_reports_wrong_graph_without_publishing(tmp_path, monkeypatch):
    config = BulkRecordingConfig(graph_manifest_sha256='a' * 64,
                                 simulation=example()['simulation'])
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: SimpleNamespace(provenance={'manifest_sha256': 'b' * 64}))
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='graph mismatch'):
        run_bulk_recording_child({'execution_id': str(uuid4()),
                                  'config': config.model_dump(mode='json')}, str(output))
    assert (output / 'error.json').exists()
    assert not (output / 'manifest.json').exists()


def test_dispatch_is_idempotent_exclusive_and_cancellable(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.process.mp.get_context',
                        lambda _: SimpleNamespace(Process=FakeProcess))
    manager = Executions(tmp_path)
    config = BulkRecordingConfig(graph_manifest_sha256='a' * 64,
                                 simulation=example()['simulation'])
    first = BulkRecordingExecutionRequest(execution_id=uuid4(), config=config)
    second = BulkRecordingExecutionRequest(execution_id=uuid4(), config=config)
    started = manager.start_bulk_recording(first)
    assert started['kind'] == 'experimental-independent-population'
    assert manager.start_bulk_recording(first) == started
    with pytest.raises(RuntimeError, match='busy'):
        manager.start_bulk_recording(second)
    changed = config.model_copy(update={'graph_manifest_sha256': 'b' * 64})
    with pytest.raises(ValueError, match='another configuration'):
        manager.start_bulk_recording(first.model_copy(update={'config': changed}))
    assert manager.cancel(str(first.execution_id))['status'] == 'cancelled'
    assert manager.start_bulk_recording(second)['status'] == 'running'


def test_private_http_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.process.mp.get_context',
                        lambda _: SimpleNamespace(Process=FakeProcess))
    manager = Executions(tmp_path)
    client = TestClient(build_app(manager, 'a' * 32, lambda: True))
    config = BulkRecordingConfig(graph_manifest_sha256='a' * 64,
                                 simulation=example()['simulation'])
    request = BulkRecordingExecutionRequest(execution_id=uuid4(), config=config)
    path = '/v1/independent-population-executions'
    assert client.post(path, json=request.model_dump(mode='json')).status_code == 401
    auth = {'Authorization': 'Bearer ' + 'a' * 32}
    response = client.post(path, json=request.model_dump(mode='json'), headers=auth)
    assert response.status_code == 200
    assert response.json()['kind'] == 'experimental-independent-population'
    assert client.post(path, json=request.model_dump(mode='json'), headers=auth).json() == (
        response.json())
    cancelled = client.post(f'/v1/executions/{request.execution_id}/cancel', headers=auth)
    assert cancelled.json()['status'] == 'cancelled'


def test_private_validation_checks_graph_and_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: SimpleNamespace(provenance={'manifest_sha256': 'a' * 64}))
    client = TestClient(build_app(Executions(tmp_path), 'a' * 32, lambda: True))
    config = BulkRecordingConfig(graph_manifest_sha256='a' * 64,
                                 simulation=example()['simulation'])
    auth = {'Authorization': 'Bearer ' + 'a' * 32}
    response = client.post('/v1/independent-population-validate',
                           json=config.model_dump(mode='json'), headers=auth)
    assert response.status_code == 200
    assert response.json()['configuration_sha256'] == config.digest()
    wrong = config.model_copy(update={'graph_manifest_sha256': 'b' * 64})
    assert client.post('/v1/independent-population-validate',
                       json=wrong.model_dump(mode='json'), headers=auth).status_code == 409
