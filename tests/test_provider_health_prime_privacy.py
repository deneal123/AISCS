"""Fail-soft health priming preserves the last snapshot without leaking provider errors."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest

from service.services.admin.application import admin_service
from service.services.admin.application.admin_service import AdminService


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("stage", ["discovery", "overlay"])
async def test_failed_prime_preserves_cache_and_emits_only_bounded_diagnostic(
    monkeypatch, cached, stage
):
    snapshot = {
        "active_provider": "gigachat",
        "providers": {"gigachat": {"configured": True, "reachable": True}},
    }
    cache = {"ts": 123.0 if cached else 0.0, "data": deepcopy(snapshot) if cached else None}
    before = deepcopy(cache)
    monkeypatch.setattr(admin_service, "_HEALTH_CACHE", cache)
    logger = Mock()
    monkeypatch.setattr(admin_service, "logger", logger)
    service = AdminService.__new__(AdminService)
    marker = "PRIVATE-PROVIDER-BODY-credential"
    discovery = AsyncMock(return_value=snapshot)
    overlay = Mock(return_value=snapshot)
    if stage == "discovery":
        discovery.side_effect = RuntimeError(marker)
    else:
        overlay.side_effect = RuntimeError(marker)
    monkeypatch.setattr(service, "_compute_provider_health", discovery)
    monkeypatch.setattr(service, "_apply_disabled_overlay", overlay)

    await service.prime_provider_health()

    assert cache == before
    discovery.assert_awaited_once_with()
    logger.debug.assert_called_once_with(
        "provider health prime failed",
        extra={"component": "provider_health", "failure_code": "unavailable"},
    )
    assert marker not in repr(logger.mock_calls)


@pytest.mark.asyncio
async def test_cancelled_prime_is_not_swallowed_or_cached(monkeypatch):
    cache = {"ts": 0.0, "data": None}
    monkeypatch.setattr(admin_service, "_HEALTH_CACHE", cache)
    logger = Mock()
    monkeypatch.setattr(admin_service, "logger", logger)
    service = AdminService.__new__(AdminService)
    discovery = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(service, "_compute_provider_health", discovery)
    with pytest.raises(asyncio.CancelledError):
        await service.prime_provider_health()
    assert cache == {"ts": 0.0, "data": None}
    logger.debug.assert_not_called()
