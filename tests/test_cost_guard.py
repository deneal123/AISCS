from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from service.services.billing.application.billing_service import BillingService
from service.services.billing.application.cost_guard import (
    cleanup_expired_reservations,
    cost_guard_status,
)
from service.services.billing.persistence.cost_guard_events import CostGuardEventsMixin


def test_cost_guard_statuses_are_actionable():
    assert (
        cost_guard_status(healthy=True, fallback_pricing=0, prompt_budget_stops=0, expired=0)[
            "level"
        ]
        == "normal"
    )
    assert (
        cost_guard_status(healthy=True, fallback_pricing=1, prompt_budget_stops=0, expired=0)[
            "level"
        ]
        == "warning"
    )
    assert (
        cost_guard_status(healthy=False, fallback_pricing=0, prompt_budget_stops=0, expired=0)[
            "level"
        ]
        == "critical"
    )
    assert (
        cost_guard_status(
            healthy=True,
            fallback_pricing=3,
            prompt_budget_stops=2,
            expired=0,
            warning_events=2,
            critical_events=5,
        )["level"]
        == "critical"
    )


class _Repo:
    def __init__(self):
        self.released = []
        self.committed = []
        self.cost_guard_since = None

    async def reserve(self, **_kwargs):
        return "reservation-1"

    async def release_reservation(self, *, reservation_id):
        self.released.append(reservation_id)

    async def cleanup_expired_reservations(self):
        return 2

    async def fetch_reservation_snapshot(self):
        return {"active": 1, "expired": 0}

    async def charge(self, **kwargs):
        self.committed.append(kwargs)
        return {"from_subscription": 10, "from_topup": 0}

    async def fetch_usage_totals(self, *, since):
        return {"credits": 10, "raw_cost_rub": 0.1, "requests": 1}

    async def fetch_cost_guard_events(self, *, since):
        self.cost_guard_since = since
        return {"fallback_pricing": 1, "prompt_budget_stops": 2, "raw_cost_rub": 12.34567}


class _CostGuardEventsRepository(CostGuardEventsMixin):
    connector = object()


class _EventsSession:
    def __init__(self):
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return SimpleNamespace(first=lambda: (2, 3, Decimal("4.5678")))


@pytest.mark.asyncio
async def test_reservation_lifecycle_and_reconcile_snapshot():
    repo = _Repo()
    service = BillingService(
        repo, SimpleNamespace(free_plan_credits=100, credit_unit_rub=0.01, min_margin=1.0)
    )
    assert await service.reserve("u", credits=10) == "reservation-1"
    await service.release_reservation("reservation-1")
    assert repo.released == ["reservation-1"]
    assert await cleanup_expired_reservations(repo) == {"expired": 0, "active": 1}
    await service.charge(
        "u",
        credits=10,
        tokens=20,
        raw_cost_rub=0.1,
        reservation_id="reservation-1",
        metadata={
            "provider": "openrouter",
            "billing_fallback": "pricing_failed_floor",
            "stop_reason": "prompt_budget_reached",
        },
    )
    reconcile = await service.reconcile(range_key="7d", today=date(2026, 1, 2))
    assert reconcile["cost_guard"]["fallback_pricing"] == 1
    assert reconcile["cost_guard"]["prompt_budget_stops"] == 2
    assert reconcile["cost_guard"]["raw_cost_rub"] == 12.3457
    assert repo.cost_guard_since is not None
    age = datetime.now(UTC) - repo.cost_guard_since
    assert timedelta(hours=23, minutes=59) < age < timedelta(hours=24, minutes=1)
    assert reconcile["status"]["level"] == "warning"


@pytest.mark.asyncio
async def test_cost_guard_events_sum_exact_usage_cost_from_events():
    session = _EventsSession()
    since = datetime(2026, 1, 2, tzinfo=UTC)

    result = await _CostGuardEventsRepository().fetch_cost_guard_events(
        since=since, session=session
    )

    assert result == {"fallback_pricing": 2, "prompt_budget_stops": 3, "raw_cost_rub": 4.5678}
    sql, params = session.calls[0]
    assert "raw_cost_rub" in sql
    assert "~" in sql  # malformed historical JSON cost must not break reconcile
    assert "profile.billing_events" in sql
    assert params == {"since": since}
