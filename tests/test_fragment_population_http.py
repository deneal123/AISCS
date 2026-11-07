import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from service.domain.contracts.fragment_population_contract import FragmentPopulationExecutionRequest
from service.infrastructure.execution.process import Executions
from service.presentation.http import build_app
from tests.test_forced_network import graph
from tests.test_fragment_population_contract import example
from tests.test_replay_execution import FakeProcess


def test_fragment_executor_auth_idempotency_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "service.infrastructure.execution.process.mp.get_context",
        lambda _: SimpleNamespace(Process=FakeProcess),
    )
    manager = Executions(tmp_path)
    client = TestClient(build_app(manager, "a" * 32, lambda: True))
    req = FragmentPopulationExecutionRequest.model_validate(
        {"execution_id": str(uuid4()), "config": example()}
    )
    body = req.model_dump(mode="json")
    assert client.post("/v1/fragment-population-executions", json=body).status_code == 401
    auth = {"Authorization": "Bearer " + "a" * 32}
    response = client.post("/v1/fragment-population-executions", json=body, headers=auth)
    assert response.status_code == 200
    assert response.json()["kind"] == "experimental-fragment-population"
    assert (
        client.post("/v1/fragment-population-executions", json=body, headers=auth).json()
        == response.json()
    )
    changed = req.model_dump(mode="json")
    changed["config"]["seed"] = 2
    assert (
        client.post("/v1/fragment-population-executions", json=changed, headers=auth).status_code
        == 409
    )
    process = manager.processes[str(req.execution_id)]
    process.alive = False
    output = tmp_path / str(req.execution_id) / "output"
    output.mkdir()
    (output / "manifest.json").write_text(json.dumps({"files": []}))
    assert manager.status(str(req.execution_id))["status"] == "completed"
    assert manager.acknowledge(str(req.execution_id), req.config.digest())["acknowledged"]
    assert not output.exists()


def test_fragment_validation_requires_matching_graph_and_known_sources(tmp_path, monkeypatch):
    model = graph()
    model.provenance["manifest_sha256"] = "a" * 64
    monkeypatch.setattr(
        "service.infrastructure.connectome.neighbors.registered_graph", lambda: model
    )
    client = TestClient(build_app(Executions(tmp_path), "a" * 32, lambda: True))
    auth = {"Authorization": "Bearer " + "a" * 32}
    body = example()
    response = client.post("/v1/fragment-population-validate", json=body, headers=auth)
    assert response.status_code == 200
    legacy_hash = response.json()['configuration_sha256']
    assert 'allow_partial_geometry' not in response.json()['configuration']
    partial = client.post('/v1/fragment-population-validate',
                          json={**body, 'allow_partial_geometry': True}, headers=auth)
    assert partial.status_code == 200
    assert partial.json()['configuration']['allow_partial_geometry'] is True
    assert partial.json()['configuration_sha256'] != legacy_hash
    body["source_ids"] = [40]
    assert (
        client.post("/v1/fragment-population-validate", json=body, headers=auth).status_code == 404
    )
    body["graph_manifest_sha256"] = "b" * 64
    assert (
        client.post("/v1/fragment-population-validate", json=body, headers=auth).status_code == 409
    )


def test_fragment_execution_respects_busy_and_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "service.infrastructure.execution.process.mp.get_context",
        lambda _: SimpleNamespace(Process=FakeProcess),
    )
    manager = Executions(tmp_path)
    first = FragmentPopulationExecutionRequest.model_validate(
        {"execution_id": str(uuid4()), "config": example()}
    )
    second = FragmentPopulationExecutionRequest.model_validate(
        {"execution_id": str(uuid4()), "config": example()}
    )
    manager.start_fragment_population(first)
    with pytest.raises(RuntimeError, match="busy"):
        manager.start_fragment_population(second)
    assert manager.cancel(str(first.execution_id))["status"] == "cancelled"
    assert manager.start_fragment_population(second)["status"] == "running"
