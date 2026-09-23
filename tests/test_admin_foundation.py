"""Тесты фундамента админки (Фаза A): реестр, runtime-overlay, admin-роль."""

import asyncio
import re
from types import SimpleNamespace

import pytest

from service.services.admin.application.admin_service import AdminRoleError, AdminService
from service.services.admin.application.runtime_settings import (
    OverlayBillingConfig,
    RuntimeSettings,
)
from service.services.admin.application.settings_registry import all_specs
from service.settings import config

# Паттерны РЕАЛЬНЫХ секретов (а не безобидных "token_budget" и т.п.).
_SECRET_RE = re.compile(
    r"(api_key|_secret|secret_key|password|authorization_key|access_key|_pass\b)", re.I
)


class _FakeRepo:
    def __init__(self, data=None, boom=False):
        self._data = data or {}
        self._boom = boom

    async def get_all(self):
        if self._boom:
            raise RuntimeError("db down")
        return dict(self._data)


# --------------------------------------------------------------------------- #
# registry — whitelist без секретов, маппинг на реальные поля config           #
# --------------------------------------------------------------------------- #
def test_registry_has_no_secret_keys():
    for spec in all_specs():
        assert not _SECRET_RE.search(spec.key), f"secret-like key leaked: {spec.key}"
        assert not _SECRET_RE.search(spec.field), f"secret-like field leaked: {spec.field}"


def test_registry_keys_map_to_real_config_fields():
    """Контракт реестра: `section.field` ключа обязан существовать в config.

    Раньше здесь был жёсткий список секций {billing, agents} — он устаревал при каждой
    новой секции (email, и т.д.), хотя проверял не тот инвариант. Реальный контракт
    (admin_service требует существования config.<section>.<field>) проверяется прямо.
    """
    for spec in all_specs():
        section = getattr(config, spec.section, None)
        assert section is not None, f"{spec.key} → нет секции config.{spec.section}"
        assert hasattr(section, spec.field), (
            f"{spec.key} → нет поля config.{spec.section}.{spec.field}"
        )


# --------------------------------------------------------------------------- #
# runtime overlay                                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_returns_default_when_unbound():
    rs = RuntimeSettings()
    assert rs.get("billing.margin_multiplier", 2.5) == 2.5


@pytest.mark.asyncio
async def test_get_returns_db_value_after_refresh():
    rs = RuntimeSettings()
    rs.bind(_FakeRepo({"billing.margin_multiplier": 3.0}))
    await rs.refresh(force=True)
    assert rs.get("billing.margin_multiplier", 2.5) == 3.0


@pytest.mark.asyncio
async def test_clamp_and_coerce():
    rs = RuntimeSettings()
    rs.bind(
        _FakeRepo(
            {
                "billing.margin_multiplier": 999,  # max 100
                "agents.max_subtasks": 99,  # max 10
                "agents.multi_intent_enabled": "true",  # bool coerce
                "billing.plan_credits": {"free": 1},  # json
            }
        )
    )
    await rs.refresh(force=True)
    assert rs.get("billing.margin_multiplier", 2.5) == 100.0
    assert rs.get("agents.max_subtasks", 3) == 10
    assert rs.get("agents.multi_intent_enabled", False) is True
    assert rs.get("billing.plan_credits", {}) == {"free": 1}


@pytest.mark.asyncio
async def test_unknown_key_returns_default():
    rs = RuntimeSettings()
    rs.bind(_FakeRepo({"billing.not_registered": 1}))
    await rs.refresh(force=True)
    assert rs.get("billing.not_registered", 7) == 7  # вне whitelist


@pytest.mark.asyncio
async def test_failopen_on_db_error():
    rs = RuntimeSettings()
    rs.bind(_FakeRepo(boom=True))
    await rs.refresh(force=True)
    assert rs.get("billing.margin_multiplier", 2.5) == 2.5  # дефолт, не падаем


def test_empty_overlay_equals_legacy_for_all_keys():
    """Контракт Фазы B: при пустом overlay каждый ключ возвращает дефолт config."""
    rs = RuntimeSettings()  # unbound = пустой overlay
    for spec in all_specs():
        default = getattr(getattr(config, spec.section), spec.field)
        assert rs.get(spec.key, default) == default
    overlay = OverlayBillingConfig(config.billing, rs)
    for spec in all_specs():
        if spec.section == "billing":
            assert getattr(overlay, spec.field) == getattr(config.billing, spec.field)


@pytest.mark.asyncio
async def test_overlay_billing_config_proxy():
    rs = RuntimeSettings()
    rs.bind(_FakeRepo({"billing.margin_multiplier": 4.0}))
    await rs.refresh(force=True)
    base = SimpleNamespace(margin_multiplier=2.5, free_plan_credits=10000, custom_field="x")
    overlay = OverlayBillingConfig(base, rs)
    assert overlay.margin_multiplier == 4.0  # из overlay (в реестре)
    assert overlay.free_plan_credits == 10000  # дефолт базы (нет override)
    assert overlay.custom_field == "x"  # не в реестре → делегирует базе


def test_refresh_survives_loop_per_task_worker():
    # celery-воркер крутит НОВЫЙ event loop на каждый таск. Лок синглтона, привязанный к
    # первому (уже закрытому) loop, ронял refresh на следующем таске с "bound to a different
    # event loop". Проверяем, что синглтон переживает несколько сменившихся loop подряд.
    rs = RuntimeSettings()
    rs.bind(_FakeRepo({"billing.margin_multiplier": 2.0}))

    for _ in range(3):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(rs.refresh(force=True))
        finally:
            loop.close()

    assert rs.get_billing("margin_multiplier", 1.0) == 2.0


def test_ensure_bound_replaces_repository_for_each_worker_loop():
    rs = RuntimeSettings()
    created: list[asyncio.AbstractEventLoop] = []

    async def bind_once() -> object:
        loop = asyncio.get_running_loop()

        def factory():
            created.append(loop)
            return _FakeRepo({"billing.margin_multiplier": len(created)})

        rs.ensure_bound(factory)
        await rs.refresh(force=True)
        return rs._repo

    repositories = []
    for _ in range(2):
        loop = asyncio.new_event_loop()
        try:
            repositories.append(loop.run_until_complete(bind_once()))
        finally:
            loop.close()

    assert len(created) == 2
    assert repositories[0] is not repositories[1]
    assert rs.get_billing("margin_multiplier", 0) == 2


# --------------------------------------------------------------------------- #
# AdminService — env bootstrap + DB-флаг                                       #
# --------------------------------------------------------------------------- #
class _AdminRepo:
    def __init__(self, flag=False):
        self.flag = flag
        self.set_calls = []

    async def fetch_is_admin(self, *, user_id):
        return self.flag

    async def set_is_admin(self, *, user_id, is_admin):
        self.set_calls.append((user_id, is_admin))
        return True


@pytest.mark.asyncio
async def test_is_admin_env_short_circuit(monkeypatch):
    monkeypatch.setattr(config.service, "admin_user_ids", ["env-admin"])
    svc = AdminService(_AdminRepo(flag=False), None)
    assert await svc.is_admin("ENV-Admin") is True  # case-insensitive env


@pytest.mark.asyncio
async def test_is_admin_db_flag(monkeypatch):
    monkeypatch.setattr(config.service, "admin_user_ids", [])
    svc = AdminService(_AdminRepo(flag=True), None)
    assert await svc.is_admin("someone") is True


@pytest.mark.asyncio
async def test_is_admin_false_when_neither(monkeypatch):
    monkeypatch.setattr(config.service, "admin_user_ids", [])
    svc = AdminService(_AdminRepo(flag=False), None)
    assert await svc.is_admin("nobody") is False


@pytest.mark.asyncio
async def test_set_role_blocks_env_demotion(monkeypatch):
    monkeypatch.setattr(config.service, "admin_user_ids", ["boss"])
    svc = AdminService(_AdminRepo(), None)
    with pytest.raises(AdminRoleError):
        await svc.set_role(user_id="boss", is_admin=False)


@pytest.mark.asyncio
async def test_set_role_grants_and_invalidates(monkeypatch):
    monkeypatch.setattr(config.service, "admin_user_ids", [])
    repo = _AdminRepo()
    svc = AdminService(repo, None)
    ok = await svc.set_role(user_id="u1", is_admin=True)
    assert ok is True
    assert repo.set_calls == [("u1", True)]
