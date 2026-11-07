import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from service.domain.contracts.field_graph_contract import FieldGraphExecutionRequest
from service.infrastructure.execution.process import Executions
from service.presentation.http import build_app
from tests.test_field_graph_contract import payload
from tests.test_forced_network import graph
from tests.test_replay_execution import FakeProcess


def request(execution):
    return FieldGraphExecutionRequest.model_validate(
        {"execution_id": str(execution), "config": payload()}
    )


def test_service_authorization_idempotency_and_completed_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "service.infrastructure.execution.process.mp.get_context",
        lambda _: SimpleNamespace(Process=FakeProcess),
    )
    manager = Executions(tmp_path)
    client = TestClient(build_app(manager, "a" * 32, lambda: True))
    req = request(uuid4())
    body = req.model_dump(mode="json")
    assert client.post("/v1/field-graph-executions", json=body).status_code == 401
    auth = {"Authorization": "Bearer " + "a" * 32}
    response = client.post("/v1/field-graph-executions", json=body, headers=auth)
    assert response.status_code == 200 and response.json()["kind"] == "field-graph-replay"
    assert (
        client.post("/v1/field-graph-executions", json=body, headers=auth).json() == response.json()
    )
    changed = request(req.execution_id).model_dump(mode="json")
    changed["config"]["seed"] = 2
    assert client.post("/v1/field-graph-executions", json=changed, headers=auth).status_code == 409
    process = manager.processes[str(req.execution_id)]
    process.alive = False
    output = tmp_path / str(req.execution_id) / "output"
    output.mkdir()
    (output / "manifest.json").write_text(json.dumps({"files": []}))
    assert manager.status(str(req.execution_id))["status"] == "completed"
    assert manager.acknowledge(str(req.execution_id), req.config.digest())["acknowledged"]
    assert not output.exists()


def test_service_rejects_invalid_field_graph_input(tmp_path):
    client = TestClient(build_app(Executions(tmp_path), "a" * 32, lambda: True))
    body = request(uuid4()).model_dump(mode="json")
    body["config"]["replay_ids"] = [10]
    response = client.post(
        "/v1/field-graph-executions", json=body, headers={"Authorization": "Bearer " + "a" * 32}
    )
    assert response.status_code == 422


def test_validation_checks_graph_identity_and_neuron_membership(tmp_path, monkeypatch):
    model = graph()
    model.provenance["manifest_sha256"] = "a" * 64
    monkeypatch.setattr("service.infrastructure.connectome.neighbors.registered_graph",
                        lambda: model)
    client = TestClient(build_app(Executions(tmp_path), "a" * 32, lambda: True))
    auth = {"Authorization": "Bearer " + "a" * 32}
    body = payload()
    response = client.post("/v1/field-graph-validate", json=body, headers=auth)
    assert response.status_code == 200
    assert response.json()["configuration_sha256"] == FieldGraphExecutionRequest.model_validate(
        {"execution_id": str(uuid4()), "config": body}
    ).config.digest()
    body["replay_ids"] = [40]
    assert client.post("/v1/field-graph-validate", json=body, headers=auth).status_code == 404


def test_different_kind_cannot_reuse_execution_id(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "service.infrastructure.execution.process.mp.get_context",
        lambda _: SimpleNamespace(Process=FakeProcess),
    )
    manager, req = Executions(tmp_path), request(uuid4())
    manager.start_field_graph(req)
    with pytest.raises(ValueError, match="another configuration"):
        manager.start_field_graph(
            req.model_copy(update={"config": req.config.model_copy(update={"seed": 2})})
        )
