"""Тесты Admin API (Фаза C): настройки, пользователи, аналитика, require_admin."""

import pytest
from fastapi.testclient import TestClient

from service.models.auth_models import AuthProfile, UserTypes
from service.services.admin.application.admin_service import (
    AdminRoleError,
    AdminService,
    SettingError,
)


class _FakeAdminRepo:
    def __init__(self):
        self.adjusts = []
        self.roles = []
        self._admin = {}

    async def fetch_is_admin(self, *, user_id):
        return self._admin.get(str(user_id).lower(), False)

    async def set_is_admin(self, *, user_id, is_admin):
        self.roles.append((user_id, is_admin))
        return True

    async def list_users(self, *, query, limit, offset):
        return [{"id": "u1", "email": "a@b.c", "topup_credit_balance": 100, "is_admin": False}]

    async def get_user(self, *, user_id):
        return {"id": user_id, "email": "a@b.c"} if user_id == "u1" else None

    async def adjust_topup_credits(self, *, user_id, delta, reason, updated_by):
        self.adjusts.append((user_id, delta, reason, updated_by))
        return max(0, 100 + delta)

    # --- аналитика: пустые срезы нужного ТИПА ---------------------------------- #
    # system_analytics() собирает отчёт из 14 запросов через asyncio.gather. Фейк обязан
    # покрывать их все: пропущенный метод падает AttributeError'ом ещё до сборки отчёта,
    # и тест формы отчёта не проверяет ничего. Возвращаем пустые данные правильного типа
    # (список/словарь) — так проверяется, что отчёт собирается и на пустой базе.
    async def fetch_usage_daily_all(self, *, since):
        return []

    async def fetch_usage_events_all(self, *, since):
        return []

    async def fetch_recent_flags(self, *, limit):
        return []

    async def fetch_revenue_daily(self, *, since):
        return []

    async def fetch_cost_daily(self, *, since):
        return []

    async def fetch_new_users_daily(self, *, since):
        return []

    async def fetch_activity_hourly(self, *, since):
        return []

    async def fetch_activity_weekday(self, *, since):
        return []

    async def fetch_plan_distribution(self):
        return []

    async def fetch_sales_breakdown(self, *, since):
        return []

    async def fetch_top_users(self, *, since, limit=10):
        return []

    async def fetch_user_totals(self):
        return {"total": 0, "active": 0, "paying": 0, "admins": 0, "verified": 0}

    async def fetch_finance_windows(self):
        empty = {"revenue_rub": 0.0, "refund_rub": 0.0}
        return {"today": dict(empty), "week": dict(empty), "month": dict(empty)}

    async def fetch_cost_windows(self):
        return {"today": 0.0, "week": 0.0, "month": 0.0}

    async def fetch_period_counts(self, *, since):
        return {"paying_customers": 0, "active_users": 0}


class _FakeSettingsRepo:
    def __init__(self, data=None):
        self.data = data or {}
        self.upserts = []
        self.deletes = []

    async def get_all(self):
        return dict(self.data)

    async def upsert(self, *, key, value, updated_by):
        self.upserts.append((key, value, updated_by))
        self.data[key] = value

    async def delete(self, *, key):
        self.deletes.append(key)
        self.data.pop(key, None)


def _svc(settings_data=None):
    return AdminService(_FakeAdminRepo(), _FakeSettingsRepo(settings_data))


# --------------------------------------------------------------------------- #
# settings                                                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_set_setting_unknown_key_rejected():
    svc = _svc()
    with pytest.raises(SettingError):
        await svc.set_setting(key="billing.nope", value=1, updated_by="admin")


@pytest.mark.asyncio
async def test_set_setting_clamps_and_persists():
    svc = _svc()
    out = await svc.set_setting(key="billing.margin_multiplier", value=999, updated_by="admin")
    assert out["value"] == 100.0  # clamp до max
    assert svc._settings_repo.upserts[-1] == ("billing.margin_multiplier", 100.0, "admin")


@pytest.mark.asyncio
async def test_set_setting_bad_bool_rejected():
    svc = _svc()
    with pytest.raises(SettingError):
        await svc.set_setting(key="agents.multi_intent_enabled", value="maybe", updated_by="a")


@pytest.mark.asyncio
async def test_get_settings_view_marks_overridden():
    svc = _svc({"billing.margin_multiplier": 5.0})
    view = await svc.get_settings_view()
    by_key = {s["key"]: s for s in view["settings"]}
    assert by_key["billing.margin_multiplier"]["value"] == 5.0
    assert by_key["billing.margin_multiplier"]["overridden"] is True
    assert by_key["billing.min_margin"]["overridden"] is False


@pytest.mark.asyncio
async def test_reset_setting_unknown_rejected():
    svc = _svc()
    with pytest.raises(SettingError):
        await svc.reset_setting(key="nope")


# --------------------------------------------------------------------------- #
# users                                                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_adjust_credits_audits():
    svc = _svc()
    out = await svc.adjust_credits(user_id="u1", delta=-50, reason="refund", updated_by="admin")
    assert out["topup_credit_balance"] == 50
    assert svc._admin_repo.adjusts == [("u1", -50, "refund", "admin")]


@pytest.mark.asyncio
async def test_set_role_env_demotion_blocked(monkeypatch):
    from service.settings import config

    monkeypatch.setattr(config.service, "admin_user_ids", ["boss"])
    svc = _svc()
    with pytest.raises(AdminRoleError):
        await svc.set_role(user_id="boss", is_admin=False)


@pytest.mark.asyncio
async def test_system_analytics_shape():
    svc = _svc()
    out = await svc.get_system_analytics(range_key="30d")
    assert out["range"] == "30d"
    assert "totals" in out and "abuse_flags" in out and "status" in out


# --------------------------------------------------------------------------- #
# router (TestClient)                                                          #
# --------------------------------------------------------------------------- #
def _admin_profile():
    return AuthProfile(
        user_id="22222222-2222-2222-2222-222222222222", fingerprint=None, type=UserTypes.REGISTERED
    )


def test_settings_endpoints_require_admin():
    from service.main import app
    from service.shared.security.auth_checker import check_auth

    app.dependency_overrides[check_auth] = lambda: _admin_profile()
    try:
        client = TestClient(app)
        assert client.get("/api/admin/settings").status_code == 403
    finally:
        app.dependency_overrides.pop(check_auth, None)


def test_admin_settings_and_users_flow():
    from service.composition.state import get_admin_service
    from service.main import app
    from service.services.admin.presentation.deps import require_admin

    svc = _svc()
    app.dependency_overrides[require_admin] = lambda: _admin_profile()
    app.dependency_overrides[get_admin_service] = lambda: svc
    try:
        client = TestClient(app)

        assert client.get("/api/admin/settings").status_code == 200

        ok = client.put(
            "/api/admin/settings", json={"key": "billing.margin_multiplier", "value": 3.0}
        )
        assert ok.status_code == 200
        assert ok.json()["value"] == 3.0

        bad = client.put("/api/admin/settings", json={"key": "nope", "value": 1})
        assert bad.status_code == 422

        adj = client.post("/api/admin/users/u1/adjust-credits", json={"delta": 25, "reason": "x"})
        assert adj.status_code == 200
        assert adj.json()["topup_credit_balance"] == 125
    finally:
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(get_admin_service, None)
