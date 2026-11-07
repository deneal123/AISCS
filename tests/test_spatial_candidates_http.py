from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import numpy as np
from fastapi.testclient import TestClient

from service.main import create_app


def test_spatial_endpoint_requires_auth_and_rejects_incomplete_index(tmp_path, monkeypatch):
    path = tmp_path / "bounds.sqlite"
    path.touch()
    monkeypatch.setenv("GENERATOR_MORPHOLOGY_BOUNDS_DB", str(path))
    monkeypatch.setenv("GENERATOR_MORPHOLOGY_BOUNDS_AUDIT", str(path))
    graph = SimpleNamespace(ids=np.array([1]), provenance={"manifest_sha256": "a" * 64})
    monkeypatch.setattr("service.infrastructure.connectome.neighbors.registered_graph",
                        lambda: graph)
    monkeypatch.setattr("service.infrastructure.stimulation.spatial_candidates.spatial_candidates",
                        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("incomplete")))
    client = TestClient(create_app(tmp_path, "a" * 32))
    body = {"source_um": [1, 2, 3], "return_um": [4, 5, 6], "radius_um": 10}
    assert client.post("/v1/connectome/spatial-candidates", json=body).status_code == 401
    auth = {"Authorization": "Bearer " + "a" * 32}
    response = client.post("/v1/connectome/spatial-candidates", json=body, headers=auth)
    assert response.status_code == 503
    assert client.post("/v1/connectome/spatial-candidates", json={**body, "radius_um": -1},
                       headers=auth).status_code == 422
    assert client.post("/v1/connectome/spatial-candidates", json={**body, "radius_um": True},
                       headers=auth).status_code == 422
    assert client.post("/v1/connectome/spatial-candidates",
                       json={**body, "electrode_um": [0, 0, 0]}, headers=auth).status_code == 422
    monkeypatch.setattr("service.infrastructure.stimulation.spatial_candidates.spatial_candidates",
                        lambda *args, **kwargs: {"candidates": [], "indexed": 1})
    response = client.post("/v1/connectome/spatial-candidates", json=body, headers=auth)
    assert response.status_code == 200
    assert response.json()["manifest_sha256"] == "a" * 64
    assert response.json()["configuration"]["radius_um"] == 10


def test_spatial_endpoint_limits_concurrent_searches_and_releases_slot(tmp_path, monkeypatch):
    path = tmp_path / "bounds.sqlite"
    path.touch()
    monkeypatch.setenv("GENERATOR_MORPHOLOGY_BOUNDS_DB", str(path))
    monkeypatch.setenv("GENERATOR_MORPHOLOGY_BOUNDS_AUDIT", str(path))
    graph = SimpleNamespace(ids=np.array([1]), provenance={"manifest_sha256": "a" * 64})
    monkeypatch.setattr("service.infrastructure.connectome.neighbors.registered_graph",
                        lambda: graph)
    entered, release = Event(), Event()

    def search(*_args, **_kwargs):
        entered.set()
        if not release.wait(10):
            raise ValueError("test timed out")
        return {"candidates": [], "indexed": 1}

    monkeypatch.setattr("service.infrastructure.stimulation.spatial_candidates.spatial_candidates",
                        search)
    client = TestClient(create_app(tmp_path, "a" * 32))
    body = {"source_um": [1, 2, 3], "return_um": [4, 5, 6], "radius_um": 10}
    auth = {"Authorization": "Bearer " + "a" * 32}
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.post, "/v1/connectome/spatial-candidates",
                            json=body, headers=auth)
        try:
            assert entered.wait(5)
            response = client.post("/v1/connectome/spatial-candidates", json=body, headers=auth)
            assert response.status_code == 429
        finally:
            release.set()
        assert first.result(timeout=10).status_code == 200
    response = client.post("/v1/connectome/spatial-candidates", json=body, headers=auth)
    assert response.status_code == 200
