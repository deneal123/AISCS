import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from service.domain.contracts.population.full_feedback import (
    FullFeedbackConfig,
    FullFeedbackExecutionRequest,
)
from service.infrastructure.execution.process import Executions, run_full_feedback_child
from service.presentation.http import build_app
from tests.test_fragment_population_contract import example
from tests.test_replay_execution import FakeProcess


def config():
    synapse = {'weight_us': .01, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}
    return FullFeedbackConfig(graph_manifest_sha256='a' * 64, simulation=example()['simulation'],
        excitatory=synapse, inhibitory={**synapse, 'reversal_mv': -80.}, threshold_mv=-20.,
        max_source_distance_um=2., max_target_distance_um=2., max_iterations=3, max_events=100)


def test_full_feedback_lifecycle_and_cancel_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.process.mp.get_context',
                        lambda _: SimpleNamespace(Process=FakeProcess))
    manager = Executions(tmp_path)
    first = FullFeedbackExecutionRequest(execution_id=uuid4(), config=config())
    second = FullFeedbackExecutionRequest(execution_id=uuid4(), config=config())
    record = manager.start_full_feedback(first)
    assert manager.start_full_feedback(first) == record
    with pytest.raises(RuntimeError, match='busy'):
        manager.start_full_feedback(second)
    scratch = tmp_path / str(first.execution_id) / '.feedback-sources-test'
    scratch.mkdir()
    (scratch / 'test').write_text('scratch')
    assert manager.cancel(str(first.execution_id))['status'] == 'cancelled'
    assert not scratch.exists()
    assert manager.start_full_feedback(second)['status'] == 'running'


def test_child_rejects_result_without_request_identity(tmp_path, monkeypatch):
    monkeypatch.setenv('GENERATOR_SYNAPSE_DIR', 'configured')
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: SimpleNamespace(provenance={'manifest_sha256': 'a' * 64}))
    monkeypatch.setattr('service.infrastructure.connectome.synapse_repository.registered_index',
                        lambda *_a: object())
    monkeypatch.setattr('service.infrastructure.execution.process._field_geometry_cache',
                        lambda *_a: {})

    def fake_execute(*_args, solver_options, output_directory, **_kwargs):
        output_directory.mkdir()
        path = output_directory / 'manifest.json'
        path.write_text(json.dumps({'configuration': {'request_sha256': '0' * 64},
            'batch_settings': solver_options,
            'solver_kernels': {'accelerated_cell_major': 1, 'generic': 0, 'batches': 1}}))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {'status': 'converged', 'manifest_sha256': digest}

    monkeypatch.setattr('service.application.population.full_feedback_experiment.'
                        'execute_full_feedback_request', fake_execute)
    request = FullFeedbackExecutionRequest(execution_id=uuid4(), config=config())
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='identity mismatch'):
        run_full_feedback_child(request.model_dump(mode='json'), str(output))
    assert (output / 'error.json').exists()


def _published_child(monkeypatch, manifest_update):
    monkeypatch.setenv('GENERATOR_SYNAPSE_DIR', 'configured')
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: SimpleNamespace(provenance={'manifest_sha256': 'a' * 64}))
    monkeypatch.setattr('service.infrastructure.connectome.synapse_repository.registered_index',
                        lambda *_a: object())
    monkeypatch.setattr('service.infrastructure.execution.process._field_geometry_cache',
                        lambda *_a: {})
    seen = {}

    def fake_execute(_graph, _index, config, *, solver_options, output_directory, **_kwargs):
        seen.update(solver_options)
        output_directory.mkdir()
        path = output_directory / 'manifest.json'
        manifest = {'configuration': {'request_sha256': config.digest()},
                    'batch_settings': solver_options,
                    'solver_kernels': {'accelerated_cell_major': 1, 'generic': 0,
                                       'batches': 1}}
        manifest.update(manifest_update(solver_options))
        path.write_text(json.dumps(manifest))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {'status': 'converged', 'manifest_sha256': digest}

    monkeypatch.setattr('service.application.population.full_feedback_experiment.'
                        'execute_full_feedback_request', fake_execute)
    return seen


def test_child_requires_the_accelerated_cell_major_kernel(tmp_path, monkeypatch):
    seen = _published_child(monkeypatch,
        lambda settings: {'solver_kernels': {'accelerated_cell_major': 0, 'generic': 3,
                                             'batches': 3}})
    request = FullFeedbackExecutionRequest(execution_id=uuid4(), config=config())
    with pytest.raises(ValueError, match='accelerated cell-major kernel'):
        run_full_feedback_child(request.model_dump(mode='json'), str(tmp_path / 'output'))
    # The connected experiment must not inherit the small independent defaults.
    assert seen['require_cell_major'] is True
    assert seen['max_cells'] > 20 and seen['segment_budget'] > 200000


def test_child_rejects_a_manifest_with_other_batch_settings(tmp_path, monkeypatch):
    _published_child(monkeypatch, lambda settings: {'batch_settings': {**settings,
        'max_cells': settings['max_cells'] - 1}})
    request = FullFeedbackExecutionRequest(execution_id=uuid4(), config=config())
    with pytest.raises(ValueError, match='batch settings mismatch'):
        run_full_feedback_child(request.model_dump(mode='json'), str(tmp_path / 'output'))


def test_private_http_start_and_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.process.mp.get_context',
                        lambda _: SimpleNamespace(Process=FakeProcess))
    client = TestClient(build_app(Executions(tmp_path), 'a' * 32, lambda: True))
    request = FullFeedbackExecutionRequest(execution_id=uuid4(), config=config())
    path = '/v1/full-population-feedback-executions'
    assert client.post(path, json=request.model_dump(mode='json')).status_code == 401
    auth = {'Authorization': 'Bearer ' + 'a' * 32}
    response = client.post(path, json=request.model_dump(mode='json'), headers=auth)
    assert response.status_code == 200
    assert response.json()['kind'] == 'experimental-full-population-feedback'
    assert client.post(f'/v1/executions/{request.execution_id}/cancel', headers=auth).json()[
        'status'] == 'cancelled'


def test_private_http_validates_graph_and_returns_population_size(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: SimpleNamespace(ids=[10, 20], provenance={
                            'manifest_sha256': 'a' * 64}))
    client = TestClient(build_app(Executions(tmp_path), 'a' * 32, lambda: True))
    auth = {'Authorization': 'Bearer ' + 'a' * 32}
    response = client.post('/v1/full-population-feedback-validate',
                           json=config().model_dump(mode='json'), headers=auth)
    assert response.status_code == 200
    assert response.json()['configuration_sha256'] == config().digest()
    assert response.json()['graph_cells'] == 2



def test_pause_is_a_request_and_a_checkpoint_makes_it_pausable(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.process.mp.get_context',
                        lambda _: SimpleNamespace(Process=FakeProcess))
    monkeypatch.setenv('GENERATOR_FULL_PAUSE', str(tmp_path / 'pause'))
    manager = Executions(tmp_path)
    req = FullFeedbackExecutionRequest(execution_id=uuid4(), config=config())
    manager.start_full_feedback(req)
    execution, root = str(req.execution_id), tmp_path / str(req.execution_id)
    assert manager.status(execution)['pause_directory'] == str(tmp_path / 'pause')
    # The resumed process is rebuilt from this file, so it must carry the request.
    assert json.loads((root / 'request.json').read_text())['execution_id'] == execution
    with pytest.raises(ValueError, match='paused'):
        manager.resume(execution)
    manager.pause(execution)
    # A request is a file, so it outlives the service and still reaches a solver
    # that has not crossed a batch boundary yet.
    assert (tmp_path / 'pause' / 'pause.requested').is_file()
    manager.processes[execution].alive = False
    (root / 'output').mkdir(parents=True, exist_ok=True)
    (root / 'pause.json').write_text(json.dumps({'checkpoint': {}, 'paused_at': 1.0}))
    assert manager.status(execution)['status'] == 'paused'
    with pytest.raises(ValueError, match='checkpoint is missing'):
        manager.resume(execution)


def test_pause_requires_a_configured_directory(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.process.mp.get_context',
                        lambda _: SimpleNamespace(Process=FakeProcess))
    monkeypatch.delenv('GENERATOR_FULL_PAUSE', raising=False)
    manager = Executions(tmp_path)
    req = FullFeedbackExecutionRequest(execution_id=uuid4(), config=config())
    manager.start_full_feedback(req)
    with pytest.raises(ValueError, match='configured pause directory'):
        manager.pause(str(req.execution_id))
