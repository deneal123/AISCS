import hashlib
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from service.infrastructure.execution.process import Executions
from service.presentation.http import build_app
from tests.test_replay_execution import FakeProcess


def configuration():
    synapse = {'weight_us': .001, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}
    return {'graph_manifest_sha256': 'a' * 64, 'source_package_sha256': 'b' * 64,
            'source_manifest_sha256': 'c' * 64, 'excitatory': synapse,
            'inhibitory': {**synapse, 'reversal_mv': -80.}, 'max_iterations': 5,
            'allow_partial_geometry': False}


def test_feedback_execution_auth_idempotency_busy_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.process.mp.get_context',
                        lambda _: SimpleNamespace(Process=FakeProcess))
    manager = Executions(tmp_path)
    client = TestClient(build_app(manager, 'a' * 32, lambda: True))
    eid = uuid4()
    data = b'checked when executed'
    config = {**configuration(), 'source_package_sha256': hashlib.sha256(data).hexdigest()}
    body = {'execution_id': str(eid), 'config': config}
    url = '/v1/population-feedback-executions'
    auth = {'Authorization': 'Bearer ' + 'a' * 32}
    assert client.post(url, json=body).status_code == 401
    assert client.post(url, json=body, headers=auth).status_code == 409
    source = tmp_path / str(eid) / 'replay-input.bin'
    source.parent.mkdir(parents=True)
    source.write_bytes(data)
    response = client.post(url, json=body, headers=auth)
    assert response.status_code == 200
    assert response.json()['kind'] == 'experimental-coupled-population'
    assert client.post(url, json=body, headers=auth).json() == response.json()
    assert client.post(url, json={**body, 'config': {**config, 'max_iterations': 6}},
                       headers=auth).status_code == 409
    assert client.post(url, json={'execution_id': str(uuid4()), 'config': config},
                       headers=auth).status_code == 503
    temporary = source.parent / 'feedback-replay-test'
    temporary.mkdir()
    (temporary / 'intermediate').write_bytes(b'temporary')
    assert manager.cancel(str(eid))['status'] == 'cancelled'
    assert not temporary.exists() and source.exists()
    manager.discard(str(eid), response.json()['configuration_sha256'])
    assert not source.exists()


def test_feedback_validation_rejects_bad_graph_and_kinetics(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: SimpleNamespace(provenance={'manifest_sha256': 'a' * 64}))
    client = TestClient(build_app(Executions(tmp_path), 'a' * 32, lambda: True))
    auth = {'Authorization': 'Bearer ' + 'a' * 32}
    url = '/v1/population-feedback-validate'
    assert client.post(url, json=configuration()).status_code == 401
    assert client.post(url, json=configuration(), headers=auth).status_code == 200
    assert client.post(url, json={**configuration(), 'graph_manifest_sha256': 'd' * 64},
                       headers=auth).status_code == 409
    invalid = {**configuration(), 'max_iterations': True}
    assert client.post(url, json=invalid, headers=auth).status_code == 422


def test_discretization_validation_preserves_legacy_contract(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: SimpleNamespace(provenance={'manifest_sha256': 'a' * 64}))
    client = TestClient(build_app(Executions(tmp_path), 'a' * 32, lambda: True))
    auth = {'Authorization': 'Bearer ' + 'a' * 32}
    url = '/v1/population-feedback-validate'
    legacy = client.post(url, json=configuration(), headers=auth).json()
    assert legacy['configuration'] == configuration()
    policy = {'max_shift_um': 2., 'max_observation_distance_um': 2., 'max_nseg': 9}
    refined = client.post(url, json={**configuration(), 'discretization': policy}, headers=auth)
    assert refined.status_code == 200
    assert refined.json()['configuration']['discretization'] == policy
    assert refined.json()['configuration_sha256'] != legacy['configuration_sha256']
    invalid = {**policy, 'max_nseg': 2}
    assert client.post(url, json={**configuration(), 'discretization': invalid},
                       headers=auth).status_code == 422
    invalid = {**configuration(), 'excitatory': {**configuration()['excitatory'], 'tau1_ms': 3.}}
    assert client.post(url, json=invalid, headers=auth).status_code == 422


def test_acknowledging_feedback_removes_private_source(tmp_path):
    manager = Executions(tmp_path)
    eid, data = uuid4(), b'private input'
    source = tmp_path / str(eid) / 'replay-input.bin'
    source.parent.mkdir(parents=True)
    source.write_bytes(data)
    manager.save({'execution_id': str(eid), 'kind': 'experimental-coupled-population',
                  'status': 'completed', 'configuration_sha256': 'd' * 64,
                  'source_sha256': hashlib.sha256(data).hexdigest(), 'acknowledged': False})
    assert manager.acknowledge(str(eid), 'd' * 64)['acknowledged']
    assert not source.exists()
