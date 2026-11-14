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

    def fake_execute(*_args, output_directory, **_kwargs):
        output_directory.mkdir()
        path = output_directory / 'manifest.json'
        path.write_text(json.dumps({'configuration': {'request_sha256': '0' * 64}}))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {'status': 'converged', 'manifest_sha256': digest}

    monkeypatch.setattr('service.application.population.full_feedback_experiment.'
                        'execute_full_feedback_request', fake_execute)
    request = FullFeedbackExecutionRequest(execution_id=uuid4(), config=config())
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='identity mismatch'):
        run_full_feedback_child(request.model_dump(mode='json'), str(output))
    assert (output / 'error.json').exists()


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
