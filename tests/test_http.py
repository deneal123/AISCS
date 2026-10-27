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
