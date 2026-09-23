from decimal import Decimal

import pytest

from service.services.billing.application.provider_catalog import ProviderPricingCatalog
from service.services.billing.application.provider_pricing_sync import ProviderPricingSyncService
from service.services.billing.persistence.billing_repository import BillingRepository
from tests.test_helpers import FakeConnector, FakeDBSession


@pytest.mark.asyncio
async def test_sync_fetches_before_the_single_atomic_replace() -> None:
    seen: list[list[dict]] = []

    class _Repo:
        async def replace_synced_pricing(self, *, catalogs):
            seen.append(catalogs)
            return {"providers": 2, "replaced": 2, "deleted": 1}

    catalogs = [
        ProviderPricingCatalog(
            "routerai",
            [("provider/model", Decimal("1"), Decimal("2"))],
            "sync:routerai:2026-08-06",
        ),
        ProviderPricingCatalog(
            "openrouter",
            [("provider/model", Decimal("3"), Decimal("4"))],
            "sync:openrouter:2026-08-06:cbr-usd-81",
        ),
    ]
    service = ProviderPricingSyncService(_Repo(), fetch_catalogs=lambda: catalogs)

    assert await service.refresh() == {"providers": 2, "replaced": 2, "deleted": 1}
    assert [item["provider"] for item in seen[0]] == ["routerai", "openrouter"]
    assert seen[0][0]["source"] == "sync:routerai:2026-08-06"


@pytest.mark.asyncio
async def test_repository_uses_one_session_for_all_catalogs() -> None:
    session = FakeDBSession()
    repo = BillingRepository(FakeConnector(session))

    result = await repo.replace_synced_pricing(
        catalogs=[
            {
                "provider": "routerai",
                "rows": [("provider/model", Decimal("1"), Decimal("2"))],
                "source": "sync:routerai:2026-08-06",
            },
            {
                "provider": "openrouter",
                "rows": [("provider/model", Decimal("3"), Decimal("4"))],
                "source": "sync:openrouter:2026-08-06:cbr-usd-81",
            },
        ]
    )

    assert result == {"providers": 2, "replaced": 2, "deleted": 0}
    assert session._committed is True
    assert len(session.executed) == 4
    assert "DELETE FROM profile.model_pricing" in session.executed[0][0]
    assert session.executed[1][1][0]["source_prefix"] == "sync:routerai:%"
