from fastapi.testclient import TestClient

from service.main import create_app


def test_metrics_endpoint_exports_billing_guard_metrics() -> None:
    response = TestClient(create_app()).get("/api/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "billing_prompt_budget_stops_total" in response.text
    assert "billing_pricing_fallbacks_total" in response.text
    assert "billing_reservation_events_total" in response.text
    assert "user_id" not in response.text
