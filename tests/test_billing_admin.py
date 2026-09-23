"""Фаза 7 (админ): управление price-registry + сверка маржи (reconcile)."""

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from service.services.billing.application.billing_service import BillingService, compute_reconcile
from service.services.billing.persistence.billing_repository import BillingRepository
from tests.test_helpers import FakeConnector, FakeDBSession


# --------------------------------------------------------------------------- #
# compute_reconcile (чистая)                                                  #
# --------------------------------------------------------------------------- #
def test_billing_repository_has_methods_used_by_service():
    """Контракт: BillingService дёргает self._repo.* — у реального BillingRepository
    эти методы должны существовать (live-чек показал, что upsert_model_pricing
    отсутствовал и админ-PUT падал в рантайме, т.к. фейки это маскировали)."""
    required = [
        "charge",
        "get_balance",
        "record_usage",
        "apply_webhook",
        "list_pricing",
        "upsert_model_pricing",
        "fetch_usage_totals",
        "fetch_usage_daily",
        "fetch_usage_events",
        "fetch_recent_events",
        "record_flag",
    ]
    for name in required:
        assert callable(getattr(BillingRepository, name, None)), f"BillingRepository.{name} missing"


def test_compute_reconcile_healthy():
    # credits=1000 × unit 0.01 = 10₽ billed; raw 4₽ → маржа 2.5 ≥ 2.0 → ок
    out = compute_reconcile(
        {"credits": 1000, "raw_cost_rub": 4.0, "requests": 5}, credit_unit_rub=0.01, min_margin=2.0
    )
    assert out["billed_rub"] == 10.0
    assert out["actual_margin"] == 2.5
    assert out["healthy"] is True


def test_compute_reconcile_unhealthy():
    # billed 10₽, raw 8₽ → маржа 1.25 < 2.0 → убыток-флаг
    out = compute_reconcile(
        {"credits": 1000, "raw_cost_rub": 8.0}, credit_unit_rub=0.01, min_margin=2.0
    )
    assert out["actual_margin"] == 1.25
    assert out["healthy"] is False


def test_compute_reconcile_no_data():
    out = compute_reconcile({"credits": 0, "raw_cost_rub": 0}, credit_unit_rub=0.01, min_margin=2.0)
    assert out["actual_margin"] is None
    assert out["healthy"] is True


# --------------------------------------------------------------------------- #
# BillingService admin methods                                                #
# --------------------------------------------------------------------------- #
class _FakeAdminRepo:
    def __init__(self):
        self.upserts = []

    async def list_pricing(self):
        return [{"model_id": "m", "price_in_rub_per_1k": 1.0, "price_out_rub_per_1k": 3.0}]

    async def upsert_model_pricing(self, **kwargs):
        self.upserts.append(kwargs)

    async def fetch_usage_totals(self, *, since):
        return {"credits": 1000, "raw_cost_rub": 4.0, "requests": 5}


@pytest.mark.asyncio
async def test_service_set_pricing_and_reconcile():
    cfg = SimpleNamespace(credit_unit_rub=0.01, min_margin=2.0)
    repo = _FakeAdminRepo()
    svc = BillingService(repo, cfg)

    await svc.set_pricing(model_id="m", price_in=1.0, price_out=3.0, updated_by="admin-1")
    assert repo.upserts[0]["model_id"] == "m"
    assert repo.upserts[0]["updated_by"] == "admin-1"

    rec = await svc.reconcile(range_key="30d", today=date(2026, 6, 26))
    assert rec["range"] == "30d"
    assert rec["actual_margin"] == 2.5
    assert rec["healthy"] is True


# --------------------------------------------------------------------------- #
# Repo list_pricing / fetch_usage_totals                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_repo_list_pricing_and_totals():
    session = FakeDBSession(
        all_map={
            "FROM profile.model_pricing": [
                ("routerai", "m", 1.0, 3.0, None, "fast", "admin", datetime(2026, 6, 1, 12, 0))
            ]
        },
        first_map={"FROM profile.usage_daily": (1000, 4.0, 5)},
    )
    repo = BillingRepository(FakeConnector(session))
    pricing = await repo.list_pricing()
    totals = await repo.fetch_usage_totals(since=date(2026, 6, 1))

    assert pricing[0]["model_id"] == "m"
    assert pricing[0]["provider"] == "routerai"
    assert pricing[0]["model_class"] == "fast"
    assert totals == {"credits": 1000, "raw_cost_rub": 4.0, "requests": 5}


# --------------------------------------------------------------------------- #
# Router: admin guard + CRUD + reconcile (TestClient)                         #
# --------------------------------------------------------------------------- #
def _admin_profile():
    from service.models.auth_models import AuthProfile
    from service.models.key_value import UserTypes

    return AuthProfile(
        user_id="11111111-1111-1111-1111-111111111111", fingerprint=None, type=UserTypes.REGISTERED
    )


def test_admin_endpoints_require_admin():
    from service.main import app
    from service.shared.security.auth_checker import check_auth

    # обычный пользователь (admin set пуст в тестах) → 403
    app.dependency_overrides[check_auth] = lambda: _admin_profile()
    try:
        client = TestClient(app)
        resp = client.get("/api/admin/billing/pricing")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(check_auth, None)


def test_admin_pricing_crud_and_reconcile():
    from service.composition.state import get_billing_service
    from service.main import app
    from service.services.billing.presentation.routers.admin_billing_api import require_admin

    # list_pricing считает эффективную цену для КАЖДОЙ модели (реестр→класс→дефолт),
    # поэтому фейковому конфигу нужны и fallback-параметры цены, а не только маржа.
    svc = BillingService(
        _FakeAdminRepo(),
        SimpleNamespace(
            credit_unit_rub=0.01,
            min_margin=2.0,
            default_price_in_rub_per_1k=2.0,
            default_price_out_rub_per_1k=6.0,
            class_prices_rub_per_1k={},
        ),
    )
    app.dependency_overrides[require_admin] = lambda: _admin_profile()
    app.dependency_overrides[get_billing_service] = lambda: svc
    try:
        client = TestClient(app)

        listing = client.get("/api/admin/billing/pricing")
        assert listing.status_code == 200
        assert listing.json()["pricing"][0]["model_id"] == "m"

        upsert = client.put(
            "/api/admin/billing/pricing",
            json={"model_id": "x", "price_in_rub_per_1k": 0.5, "price_out_rub_per_1k": 1.5},
        )
        assert upsert.status_code == 200
        assert upsert.json()["model_id"] == "x"

        reconcile = client.get("/api/admin/billing/reconcile")
        assert reconcile.status_code == 200
        assert reconcile.json()["healthy"] is True
    finally:
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(get_billing_service, None)
