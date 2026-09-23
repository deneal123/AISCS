from datetime import UTC, datetime, timedelta

from service.services.billing.application.pricing_freshness import pricing_sync_status


def test_provider_sync_status_is_actionable_and_ignores_manual_edits() -> None:
    now = datetime(2026, 8, 6, tzinfo=UTC)
    status = pricing_sync_status(
        [
            {
                "provider": "openrouter",
                "updated_by": "sync:openrouter:2026-08-06:cbr-usd-81",
                "updated_at": now - timedelta(hours=2),
            },
            {
                "provider": "routerai",
                "updated_by": "admin:manual",
                "updated_at": now,
            },
            {
                "provider": "gigachat",
                "updated_by": "system:gigachat-tariff-2026-02-01",
                "updated_at": now - timedelta(days=200),
            },
        ],
        now=now,
    )["providers"]
    by_provider = {item["provider"]: item for item in status}

    assert by_provider["openrouter"]["level"] == "normal"
    assert by_provider["openrouter"]["synced_models"] == 1
    assert by_provider["routerai"]["level"] == "critical"
    assert by_provider["routerai"]["last_synced_at"] is None
    assert by_provider["gigachat"]["level"] == "warning"
