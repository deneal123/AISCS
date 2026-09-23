"""Тумблер вкл/выкл провайдера отражается СРАЗУ (баг: чекбокс «сам возвращался»).

provider_health отдаёт закэшированный снапшот проб (обновляется только по кнопке
«Проверить»). Раньше он кэшировал и `disabled` — но disabled это чистая настройка
(provider_enabled), и после переключения тумблера GET возвращал СТАРОЕ значение, из-за
чего чекбокс в админке отскакивал назад. Теперь disabled накладывается поверх снапшота
из настройки в реальном времени.
"""

import pytest

from service.services.admin.application import admin_service as mod
from service.services.admin.application.admin_service import AdminService


def test_apply_disabled_overlay_reflects_setting(monkeypatch):
    monkeypatch.setattr(
        "service.infrastructure.provider_policy_store.disabled_providers",
        lambda: {"openai"},
    )
    snapshot = {
        "active_provider": "gigachat",
        "providers": {
            "openai": {"configured": True, "reachable": True, "disabled": False},
            "gigachat": {"configured": True, "reachable": True, "disabled": False},
        },
    }
    out = AdminService._apply_disabled_overlay(snapshot)
    assert out["providers"]["openai"]["disabled"] is True  # выключен → отражено сразу
    assert out["providers"]["gigachat"]["disabled"] is False
    # дорогие пробы из кэша сохранены (не перепроверяли)
    assert out["providers"]["openai"]["reachable"] is True


def test_disabled_unreachable_provider_does_not_keep_health_in_alarm(monkeypatch):
    """A deliberate disable removes the provider from the user-facing route."""
    monkeypatch.setattr(
        "service.infrastructure.provider_policy_store.disabled_providers",
        lambda: {"openai"},
    )
    snapshot = {
        "active_provider": "openai",
        "providers": {
            "openai": {"configured": True, "reachable": False, "disabled": False},
            "gigachat": {"configured": True, "reachable": True, "disabled": False},
        },
    }

    out = AdminService._apply_disabled_overlay(snapshot)

    assert out["providers"]["openai"]["disabled"] is True
    assert out["providers"]["openai"]["status"] == "normal"
    assert out["status"]["level"] == "normal"


@pytest.mark.asyncio
async def test_recheck_does_not_clear_breaker_for_disabled_provider(monkeypatch):
    """Disable is reversible; it must not erase a previous health blocker."""
    monkeypatch.setattr(
        "service.infrastructure.provider_policy_store.disabled_providers",
        lambda: {"openai"},
    )
    calls: list[str] = []

    async def _health(*, force_probe=False):
        assert force_probe is True
        return {
            "active_provider": "openai",
            "providers": {
                "openai": {
                    "configured": True,
                    "reachable": False,
                    "blocked": True,
                }
            },
        }

    async def _record(*_args, **_kwargs):
        calls.append("policy")

    monkeypatch.setattr("service.infrastructure.provider_policy_store.clear_blocked", _record)
    monkeypatch.setattr("service.infrastructure.provider_policy_store.set_blocked", _record)
    service = AdminService(None, None)
    monkeypatch.setattr(service, "_compute_provider_health", _health)

    out = await service.recheck_provider_health()

    assert calls == []
    assert out["providers"]["openai"]["blocked"] is True
    assert out["status"]["level"] == "normal"


@pytest.mark.asyncio
async def test_provider_health_overlays_fresh_disabled_on_cached_snapshot(monkeypatch):
    # Снапшот сделан, когда openai был ВКЛЮЧЁН.
    mod._HEALTH_CACHE.update(
        ts=1.0,
        data={
            "active_provider": "gigachat",
            "providers": {
                "openai": {"configured": True, "reachable": True, "disabled": False},
                "gigachat": {"configured": True, "reachable": True, "disabled": False},
            },
        },
    )
    # ...а теперь админ его ВЫКЛЮЧИЛ (настройка изменилась после снапшота).
    monkeypatch.setattr(
        "service.infrastructure.provider_policy_store.disabled_providers",
        lambda: {"openai"},
    )
    try:
        svc = AdminService(None, None)
        health = await svc.provider_health()
        # GET сразу отражает выключение, хотя снапшот не переснимали (без «Проверить»).
        assert health["providers"]["openai"]["disabled"] is True
        assert health["providers"]["gigachat"]["disabled"] is False
    finally:
        mod._HEALTH_CACHE.update(ts=0.0, data=None)
