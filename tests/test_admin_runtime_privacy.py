"""Runtime fallback diagnostics never expose setting values or memory responses."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from service.infrastructure import provider_policy_store
from service.infrastructure.memory import memos
from service.services.admin.application import admin_service
from service.services.admin.application import runtime_settings as runtime_module
from service.services.admin.application.admin_service import AdminService
from service.services.admin.application.runtime_settings import RuntimeSettings


@pytest.mark.asyncio
async def test_failed_refresh_preserves_stale_snapshot_and_bounded_backoff(monkeypatch):
    settings = RuntimeSettings()
    settings.bind(Mock(get_all=AsyncMock(side_effect=RuntimeError("private-setting-marker"))))
    settings._cache = {"private-setting": "private-value"}
    settings._expires_at = 0.0
    logger = Mock()
    monkeypatch.setattr(runtime_module, "logger", logger)
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: 100.0)
    await settings.refresh()
    assert settings._cache == {"private-setting": "private-value"}
    assert settings._expires_at == 105.0
    logger.debug.assert_called_once_with(
        "runtime settings refresh unavailable; retaining snapshot",
        extra={"component": "runtime_settings", "failure_code": "unavailable"},
    )
    await settings.refresh()
    settings._repo.get_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_refresh_does_not_replace_snapshot_or_backoff():
    settings = RuntimeSettings()
    settings.bind(Mock(get_all=AsyncMock(side_effect=asyncio.CancelledError())))
    settings._cache = {"setting": "value"}
    with pytest.raises(asyncio.CancelledError):
        await settings.refresh(force=True)
    assert settings._cache == {"setting": "value"}
    assert settings._expires_at == 0.0


def cascade_fixture(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(admin_service, "logger", logger)
    monkeypatch.setattr(
        admin_service.runtime_settings,
        "get_agents",
        lambda key, default: (
            "gigachat:private-current"
            if key == "memos_embedder_model"
            else [{"model": "openai:private-fallback", "dim": 1536}]
        ),
    )
    monkeypatch.setattr(provider_policy_store, "blocked_providers", AsyncMock(return_value=set()))
    monkeypatch.setattr(provider_policy_store, "disabled_providers", lambda: set())
    service = AdminService(Mock(), Mock())
    monkeypatch.setattr(service, "set_setting", AsyncMock())
    wipe = AsyncMock(return_value={"ok": True, "private-body": "private-marker"})
    monkeypatch.setattr(memos, "wipe_memos_memory", wipe)
    return service, logger, wipe


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["model", "dimension"])
async def test_cascade_failure_is_bounded_without_response_or_exception(monkeypatch, stage):
    service, logger, wipe = cascade_fixture(monkeypatch)
    failure = RuntimeError("private-cascade-marker")
    service.set_setting.side_effect = [failure] if stage == "model" else [None, failure]
    await service._cascade_memos_embedder({"gigachat"})
    logger.exception.assert_not_called()
    logger.warning.assert_called_once_with(
        "memory embedder cascade unavailable",
        extra={"component": "memory_embedder", "failure_code": "unavailable"},
    )
    assert "private" not in repr(logger.mock_calls)
    wipe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("wipe_ok", [False, True])
async def test_cascade_preserves_indexes_without_calling_wipe(monkeypatch, wipe_ok):
    service, logger, wipe = cascade_fixture(monkeypatch)
    wipe.return_value = {"ok": wipe_ok, "private-body": "private-marker"}
    await service._cascade_memos_embedder({"gigachat"})
    assert service.set_setting.await_count == 2
    logger.warning.assert_called_once_with(
        "memory embedder preference changed; index spaces remain isolated",
        extra={"component": "memory_embedder"},
    )
    wipe.assert_not_awaited()
    assert "private" not in repr(logger.mock_calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["blocked", "disabled"])
async def test_cascade_never_uses_an_unavailable_fallback(monkeypatch, policy):
    service, logger, wipe = cascade_fixture(monkeypatch)
    if policy == "blocked":
        monkeypatch.setattr(
            provider_policy_store, "blocked_providers", AsyncMock(return_value={"openai"})
        )
    else:
        monkeypatch.setattr(provider_policy_store, "disabled_providers", lambda: {"openai"})
    await service._cascade_memos_embedder({"gigachat"})
    service.set_setting.assert_not_awaited()
    wipe.assert_not_awaited()
    assert not logger.mock_calls


@pytest.mark.asyncio
async def test_cancelled_cascade_stops_before_wipe(monkeypatch):
    service, logger, wipe = cascade_fixture(monkeypatch)
    service.set_setting.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service._cascade_memos_embedder({"gigachat"})
    wipe.assert_not_awaited()
    assert not logger.mock_calls
