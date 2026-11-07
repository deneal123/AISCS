import hashlib
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
from fastapi.testclient import TestClient

from service.infrastructure.execution.process import Executions
from service.presentation.http import build_app
from tests.test_population_target_contract import valid
from tests.test_replay_execution import FakeProcess


def test_target_execution_auth_input_idempotency_and_busy(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.process.mp.get_context',
                        lambda _: SimpleNamespace(Process=FakeProcess))
    manager = Executions(tmp_path)
    client = TestClient(build_app(manager, 'a' * 32, lambda: True))
    eid = uuid4()
    data = b'verified on execution'
    config = {**valid(), 'source_package_sha256': hashlib.sha256(data).hexdigest()}
    body = {'execution_id': str(eid), 'config': config}
    url = '/v1/population-target-executions'
    auth = {'Authorization': 'Bearer ' + 'a' * 32}
    assert client.post(url, json=body).status_code == 401
    assert client.post(url, json=body, headers=auth).status_code == 409
    target = tmp_path / str(eid) / 'replay-input.bin'
    target.parent.mkdir(parents=True)
    target.write_bytes(data)
    response = client.post(url, json=body, headers=auth)
    assert response.status_code == 200
    assert response.json()['kind'] == 'experimental-one-way-target-replay'
    assert client.post(url, json=body, headers=auth).json() == response.json()
    assert client.post(url, json={**body, 'config': {**config, 'target_id': 21}},
                       headers=auth).status_code == 409
    second = {'execution_id': str(uuid4()), 'config': config}
    assert client.post(url, json=second, headers=auth).status_code == 503
    temporary = target.parent / 'target-replay-test'
    temporary.mkdir()
    (temporary / 'intermediate').write_bytes(b'temporary')
    assert manager.cancel(str(eid))['status'] == 'cancelled'
    assert not temporary.exists() and target.exists()
    manager.discard(str(eid), response.json()['configuration_sha256'])
    assert not target.exists()


def test_target_validation_checks_graph_and_all_neurons(tmp_path, monkeypatch):
    graph = SimpleNamespace(ids=np.array([10, 11, 20]), provenance={'manifest_sha256': 'a' * 64})
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: graph)
    client = TestClient(build_app(Executions(tmp_path), 'a' * 32, lambda: True))
    auth = {'Authorization': 'Bearer ' + 'a' * 32}
    url = '/v1/population-target-validate'
    assert client.post(url, json=valid()).status_code == 401
    response = client.post(url, json=valid(), headers=auth)
    assert response.status_code == 200 and len(response.json()['configuration_sha256']) == 64
    assert client.post(url, json={**valid(), 'target_id': 21}, headers=auth).status_code == 404
    assert client.post(url, json={**valid(), 'graph_manifest_sha256': 'd' * 64},
                       headers=auth).status_code == 409
