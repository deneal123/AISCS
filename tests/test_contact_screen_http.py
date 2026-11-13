from types import SimpleNamespace

import numpy as np
from fastapi.testclient import TestClient

from service.main import create_app


def test_contact_screen_requires_all_verified_indexes_and_auth(tmp_path, monkeypatch):
    keys = ('GENERATOR_MORPHOLOGY_BOUNDS_DB', 'GENERATOR_MORPHOLOGY_BOUNDS_AUDIT',
            'GENERATOR_MORPHOLOGY_RADIUS_DB', 'GENERATOR_MORPHOLOGY_RADIUS_AUDIT')
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    client = TestClient(create_app(tmp_path, 'a' * 32))
    body = {'source_um': [1, 2, 3], 'return_um': [4, 5, 6],
            'electrode_um': [7, 8, 9], 'reference_um': [10, 11, 12], 'clearance_um': 1}
    assert client.post('/v1/connectome/contact-screen', json=body).status_code == 401
    auth = {'Authorization': 'Bearer ' + 'a' * 32}
    assert client.post('/v1/connectome/contact-screen', json=body, headers=auth).status_code == 503
    assert client.post('/v1/connectome/contact-screen', json={**body, 'clearance_um': True},
                       headers=auth).status_code == 422
    for index, key in enumerate(keys):
        path = tmp_path / str(index)
        path.touch()
        monkeypatch.setenv(key, str(path))
    graph = SimpleNamespace(ids=np.array([1]), provenance={'manifest_sha256': 'a' * 64})
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: graph)
    received = []

    def screen(*args, **kwargs):
        received.append((args, kwargs))
        return {'potential_intersections': [], 'examined': 0, 'indexed': 1}

    monkeypatch.setattr('service.infrastructure.stimulation.contacts.screen.screen_contacts',
                        screen)
    response = client.post('/v1/connectome/contact-screen', json=body, headers=auth)
    assert response.status_code == 200 and response.json()['indexed'] == 1
    assert [list(point) for point in received[0][0][-2]] == [body[key] for key in (
        'source_um', 'return_um', 'electrode_um', 'reference_um')]
    assert received[0][1] == {'segment_index': None, 'segment_audit': None, 'workers': 1}
    segment, proof = tmp_path / 'segments', tmp_path / 'segment-proof'
    monkeypatch.setenv('GENERATOR_MORPHOLOGY_SEGMENT_DB', str(segment))
    monkeypatch.setenv('GENERATOR_MORPHOLOGY_SEGMENT_AUDIT', str(proof))
    response = client.post('/v1/connectome/contact-screen', json=body, headers=auth)
    assert response.status_code == 200
    assert received[1][1] == {'segment_index': segment, 'segment_audit': proof, 'workers': 1}

    positions = {'positions_um': [[1, 2, 3], [4, 5, 6], [7, 8, 9]], 'clearance_um': 1}
    assert client.post('/v1/connectome/contact-positions', json=positions).status_code == 401
    monkeypatch.setattr(
        'service.infrastructure.stimulation.contacts.screen.screen_contact_positions', screen
    )
    response = client.post('/v1/connectome/contact-positions', json=positions, headers=auth)
    assert response.status_code == 200
    assert [list(point) for point in received[2][0][-2]] == positions['positions_um']
    for invalid in ([], [[0, 0, 0]] * 65):
        response = client.post('/v1/connectome/contact-positions',
                               json={**positions, 'positions_um': invalid}, headers=auth)
        assert response.status_code == 422

    expected_cache = {'trusted': 'administrator configuration'}
    monkeypatch.setattr('service.infrastructure.execution.process._field_geometry_cache',
                        lambda _backend: expected_cache)
    response = client.post('/v1/connectome/contact-positions', json=positions, headers=auth)
    assert response.status_code == 200
    assert received[-1][1]['geometry_cache'] == expected_cache
    assert received[-1][1]['workers'] == 2

    def invalid_cache(_backend):
        raise ValueError('cache invalid')
    monkeypatch.setattr('service.infrastructure.execution.process._field_geometry_cache',
                        invalid_cache)
    assert client.post('/v1/connectome/contact-positions', json=positions,
                       headers=auth).status_code == 503
