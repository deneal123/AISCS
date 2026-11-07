import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from service.infrastructure.execution.process import Executions
from service.presentation.http import build_app
from tests.test_fragment_population_contract import example


class FakeProcess:
    def __init__(self, **_kwargs):
        self.alive = False

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive


def config():
    return {'graph_manifest_sha256': 'a' * 64, 'coordinate_frame': 'male-cns-v1.0-native-um',
            'source_um': [0., 0., 0.], 'return_um': [10., 0., 0.], 'current_na': -300.,
            'conductivity_s_m': .3, 'clearance_um': 1., 'gain': 1., 'seed': 1,
            'waveform': [0., 1., 0.], 'allow_partial_geometry': False,
            'allow_missing_curvature': False}


def test_private_validation_and_idempotent_start(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.process.mp.get_context',
                        lambda _: SimpleNamespace(Process=FakeProcess))
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: SimpleNamespace(provenance={'manifest_sha256': 'a' * 64}))
    manager = Executions(tmp_path)
    client = TestClient(build_app(manager, 'a' * 32, lambda: True))
    auth = {'Authorization': 'Bearer ' + 'a' * 32}
    body = {'execution_id': str(uuid4()), 'config': config()}
    assert client.post('/v1/field-proxy-executions', json=body).status_code == 401
    assert client.post('/v1/field-proxy-validate', json=config(), headers=auth).status_code == 200
    response = client.post('/v1/field-proxy-executions', json=body, headers=auth)
    assert response.status_code == 200 and response.json()['kind'] == 'experimental-field-proxy'
    repeated = client.post('/v1/field-proxy-executions', json=body, headers=auth)
    assert repeated.json() == response.json()
    body['config']['seed'] = 2
    assert client.post('/v1/field-proxy-executions', json=body, headers=auth).status_code == 409
    other = {**config(), 'graph_manifest_sha256': 'b' * 64}
    assert client.post('/v1/field-proxy-validate', json=other, headers=auth).status_code == 409


def test_derived_proxy_is_private_and_uses_physical_stimulus(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'service.infrastructure.connectome.neighbors',
                        SimpleNamespace(registered_graph=lambda: SimpleNamespace(
                            provenance={'manifest_sha256': 'a' * 64})))
    client = TestClient(build_app(Executions(tmp_path), 'a' * 32, lambda: True))
    request = {'population': example(), 'gain': 1., 'allow_partial_geometry': True,
               'allow_missing_curvature': True, 'allow_contact_exclusion': False}
    assert client.post('/v1/field-proxy-from-fragment', json=request).status_code == 401
    response = client.post('/v1/field-proxy-from-fragment', json=request,
                           headers={'Authorization': 'Bearer ' + 'a' * 32})
    assert response.status_code == 200
    derived = response.json()['configuration']
    assert derived['source_um'] == request['population']['simulation']['source_um']
    assert derived['waveform'][2] == pytest.approx(.8)
