from pathlib import Path

from fastapi.testclient import TestClient

from service.app import create_app
from service.core import ResearchRepository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CLIENT = TestClient(create_app(ResearchRepository(DATA)))


def test_health_publishes_read_only_contract() -> None:
    response = CLIENT.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "research"
    assert body["contract"]["read_only"] is True


def test_ready_runs_integrity_gate() -> None:
    response = CLIENT.get("/ready")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_source_not_found_uses_machine_readable_error() -> None:
    response = CLIENT.get("/v1/sources/S000000")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
