import pytest
from fastapi.testclient import TestClient

from service.main import create_app


def test_invalid_physical_contact_is_rejected_before_enqueue(tmp_path):
    client = TestClient(create_app(tmp_path, "a" * 32))
    response = client.post(
        "/v1/validate",
        headers={"Authorization": "Bearer " + "a" * 32},
        json={"placement": {"electrode": {"x_um": -85, "y_um": -35, "z_um": 0}}},
    )
    assert response.status_code == 422
    assert "outside" in response.json()["detail"]


def test_configuration_is_strict_and_service_needs_secret(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(tmp_path, "")
    client = TestClient(create_app(tmp_path, "a" * 32))
    response = client.post(
        "/v1/validate", json={"seed": True}, headers={"Authorization": "Bearer " + "a" * 32}
    )
    assert response.status_code == 422
    response = client.post(
        "/v1/validate",
        json={"conductivity_s_m": True},
        headers={"Authorization": "Bearer " + "a" * 32},
    )
    assert response.status_code == 422


def test_service_auth_and_unknown_execution(tmp_path):
    client = TestClient(create_app(tmp_path, "a" * 32))
    assert client.get("/capabilities").status_code == 401
    headers = {"Authorization": "Bearer " + "a" * 32}
    assert client.get("/capabilities", headers=headers).status_code == 200
    assert (
        client.get(
            "/v1/executions/00000000-0000-0000-0000-000000000000", headers=headers
        ).status_code
        == 404
    )


def test_unconfirmed_cancel_returns_service_unavailable(tmp_path, monkeypatch):
    from uuid import uuid4

    from service.infrastructure.execution.process import Executions
    from service.presentation.http import build_app

    manager, execution = Executions(tmp_path), str(uuid4())
    monkeypatch.setattr(manager, 'status', lambda _: {'status': 'running'})

    def fail_cancel(_):
        raise RuntimeError('Solver did not stop; cancellation is not confirmed')

    monkeypatch.setattr(manager, 'cancel', fail_cancel)
    client = TestClient(build_app(manager, 'a' * 32, lambda: True))
    response = client.post(f'/v1/executions/{execution}/cancel',
                           headers={'Authorization': 'Bearer ' + 'a' * 32})
    assert response.status_code == 503
    assert 'not confirmed' in response.json()['detail']


def test_unconfirmed_discard_returns_service_unavailable(tmp_path, monkeypatch):
    from uuid import uuid4

    from service.infrastructure.execution.process import Executions
    from service.presentation.http import build_app

    manager, execution = Executions(tmp_path), str(uuid4())
    monkeypatch.setattr(manager, 'status', lambda _: {'status': 'running'})

    def fail_discard(_, __):
        raise RuntimeError('Solver did not stop; cancellation is not confirmed')

    monkeypatch.setattr(manager, 'discard', fail_discard)
    client = TestClient(build_app(manager, 'a' * 32, lambda: True))
    response = client.post(f'/v1/executions/{execution}/discard',
                           headers={'Authorization': 'Bearer ' + 'a' * 32},
                           json={'configuration_sha256': 'b' * 64})
    assert response.status_code == 503
    assert 'not confirmed' in response.json()['detail']


def test_replay_input_upload_requires_service_auth_and_checked_hash(tmp_path):
    import hashlib
    from uuid import uuid4

    client = TestClient(create_app(tmp_path, "a" * 32))
    execution = uuid4()
    path = f"/v1/replay-inputs/{execution}"
    digest = hashlib.sha256(b"source").hexdigest()
    headers = {"Authorization": "Bearer " + "a" * 32, "X-Content-SHA256": digest}
    response = client.put(path, content=b"source", headers={"X-Content-SHA256": digest})
    assert response.status_code == 401
    assert not (tmp_path / str(execution) / "replay-input.bin").exists()
    assert client.put(path, content=b"bad", headers=headers).status_code == 422
    response = client.put(path, content=b"source", headers=headers)
    assert response.status_code == 200 and response.json() == {"sha256": digest, "bytes": 6}
    assert client.put(path, content=b"source", headers=headers).status_code == 200
    other = hashlib.sha256(b"other").hexdigest()
    response = client.put(path, content=b"other", headers={**headers, "X-Content-SHA256": other})
    assert response.status_code == 409
    assert client.delete(path, headers={"X-Content-SHA256": digest}).status_code == 401
    assert client.delete(path, headers={**headers, "X-Content-SHA256": other}).status_code == 409
    assert client.delete(path, headers=headers).json() == {"removed": True}
    assert client.delete(path, headers=headers).json() == {"removed": False}


def test_replay_input_cannot_be_removed_while_executor_runs(tmp_path, monkeypatch):
    import hashlib
    from uuid import uuid4

    from service.infrastructure.execution.process import Executions
    from service.presentation.http import build_app

    manager = Executions(tmp_path)
    monkeypatch.setattr(manager, 'status', lambda execution_id: {'status': 'running'})
    client = TestClient(build_app(manager, 'a' * 32, lambda: True))
    execution = uuid4()
    path = f'/v1/replay-inputs/{execution}'
    digest = hashlib.sha256(b'source').hexdigest()
    headers = {'Authorization': 'Bearer ' + 'a' * 32, 'X-Content-SHA256': digest}
    assert client.put(path, content=b'source', headers=headers).status_code == 200
    assert client.delete(path, headers=headers).status_code == 409
    assert (tmp_path / str(execution) / 'replay-input.bin').read_bytes() == b'source'


def test_execution_progress_is_transient_and_ignores_invalid_data(tmp_path):
    import json
    from uuid import uuid4

    from service.infrastructure.execution.process import Executions
    from service.presentation.http import build_app

    class Alive:
        def is_alive(self):
            return True

    manager = Executions(tmp_path)
    execution = str(uuid4())
    manager.save({'execution_id': execution, 'status': 'running'})
    manager.processes[execution] = Alive()
    progress_path = tmp_path / execution / 'progress.json'
    progress_path.write_text(json.dumps({'phase': 'cells', 'done': 2, 'total': 5}))
    client = TestClient(build_app(manager, 'a' * 32, lambda: True))
    response = client.get(f'/v1/executions/{execution}',
                          headers={'Authorization': 'Bearer ' + 'a' * 32})
    assert response.json()['progress'] == {'phase': 'cells', 'done': 2, 'total': 5}
    assert 'progress' not in json.loads(manager.receipt(execution).read_text())
    progress_path.write_text(json.dumps({'phase': 'cells', 'done': 6, 'total': 5}))
    assert 'progress' not in manager.status(execution)


def test_replay_validation_checks_auth_graph_and_neuron(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import numpy as np

    from service.infrastructure.connectome import neighbors
    from tests.test_replay_contract import valid

    client = TestClient(create_app(tmp_path, 'a' * 32))
    config = valid()
    headers = {'Authorization': 'Bearer ' + 'a' * 32}
    assert client.post('/v1/replay-validate', json=config).status_code == 401
    graph = SimpleNamespace(ids=np.array([12781]), provenance={'manifest_sha256': 'b' * 64})
    monkeypatch.setattr(neighbors, 'registered_graph', lambda: graph)
    assert client.post('/v1/replay-validate', json=config, headers=headers).status_code == 409
    graph.provenance['manifest_sha256'] = config['graph_manifest_sha256']
    graph.ids = np.array([1])
    assert client.post('/v1/replay-validate', json=config, headers=headers).status_code == 404
    graph.ids = np.array([12781])
    response = client.post('/v1/replay-validate', json=config, headers=headers)
    assert response.status_code == 200 and len(response.json()['configuration_sha256']) == 64


def test_morphology_distinguishes_missing_graph_from_missing_skeleton(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import numpy as np

    from service.infrastructure.connectome import neighbors

    client = TestClient(create_app(tmp_path, "a" * 32))
    headers = {"Authorization": "Bearer " + "a" * 32}

    def missing_graph():
        raise FileNotFoundError("graph")

    monkeypatch.setattr(neighbors, "registered_graph", missing_graph)
    assert client.get("/v1/connectome/morphology/42", headers=headers).status_code == 503
    monkeypatch.setattr(neighbors, "registered_graph", lambda: SimpleNamespace(ids=np.array([42])))
    monkeypatch.setenv("GENERATOR_MORPHOLOGY_DIRS", str(tmp_path))
    assert client.get("/v1/connectome/morphology/42", headers=headers).status_code == 404
    assert client.get("/v1/connectome/morphology/43", headers=headers).status_code == 404


def test_synapse_endpoint_requires_auth_and_rejects_graph_mismatch(tmp_path, monkeypatch):
    from service.infrastructure.connectome import neighbors, synapse_index, synapse_repository

    client = TestClient(create_app(tmp_path, "a" * 32))
    headers = {"Authorization": "Bearer " + "a" * 32}
    path = "/v1/connectome/neurons/42/outgoing/synapses"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers).status_code == 503
    monkeypatch.setenv("GENERATOR_SYNAPSE_DIR", str(tmp_path))
    monkeypatch.setattr(neighbors, "registered_graph", lambda: object())
    monkeypatch.setattr(synapse_repository, "registered_index", lambda *args: object())
    monkeypatch.setattr(synapse_index, "registered_page_pairs", lambda *args: {
        "counts_match": True, "body_id": "42", "direction": "outgoing", "pairs": [],
    })
    assert client.get(path, headers=headers).status_code == 200
    monkeypatch.setattr(
        synapse_index, "registered_page_pairs", lambda *args: {"counts_match": False}
    )
    assert client.get(path, headers=headers).status_code == 409
    assert client.get(path, headers=headers, params={"limit": 21}).status_code == 422


def test_native_field_endpoint_rejects_invalid_inputs_and_preserves_provenance(
    tmp_path, monkeypatch
):
    import hashlib
    import json
    from types import SimpleNamespace

    import numpy as np

    from service.infrastructure.connectome import neighbors
    from service.infrastructure.connectome.morphology_repository import BASE

    (tmp_path / "raw").mkdir()
    (tmp_path / "receipts").mkdir()
    raw = (b"1 0 0 0 0 1 -1\n2 0 125 0 0 1 1\n3 0 250 0 0 1 2\n"
           b"4 0 12500 0 0 125 -1\n")
    (tmp_path / "raw" / "42.swc").write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    (tmp_path / "receipts" / "42.json").write_text(
        json.dumps({"body_id": 42, "sha256": sha, "url": BASE + "42.swc"})
    )
    graph = SimpleNamespace(
        ids=np.array([42]), provenance={"dataset_id": "registered", "manifest_sha256": "abc"}
    )
    monkeypatch.setattr(neighbors, "registered_graph", lambda: graph)
    monkeypatch.setenv("GENERATOR_MORPHOLOGY_DIRS", str(tmp_path))
    client = TestClient(create_app(tmp_path, "a" * 32))
    headers = {"Authorization": "Bearer " + "a" * 32}
    config = {
        "source_um": [0, 10, 0],
        "return_um": [50, 10, 0],
        "current_na": 10,
        "conductivity_s_m": 0.3,
        "clearance_um": 1,
    }
    path = "/v1/connectome/morphology/42/field"
    assert client.post(path, json=config).status_code == 401
    response = client.post(path, headers=headers, json=config)
    assert response.status_code == 200
    data = response.json()
    assert data["source_sha256"] == sha and data["manifest_sha256"] == "abc"
    assert data["coordinate_frame"] == "male-cns-v1.0-native-um"
    assert data["curvature_vertex_ids"] == [2]
    assert (
        client.post(path, headers=headers, json={**config, "current_na": True}).status_code == 422
    )
    assert (
        client.post(path, headers=headers, json={**config, "source_um": [0, 0, 0]}).status_code
        == 422
    )
    assert client.post(path, headers=headers,
                       json={**config, "source_um": [101.5, 0, 0]}).status_code == 422
