"""Admin fail-soft lookups must not expose private integration diagnostics."""

import asyncio
import logging
from unittest.mock import AsyncMock, Mock

import pytest

from service.services.admin.application import admin_service
from service.services.admin.application.admin_service import AdminService


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["profile", "role", "settings"])
async def test_lookup_failure_preserves_fallback_without_exception_logging(monkeypatch, operation):
    marker = "private-admin-lookup-credential-marker"
    logger = Mock()
    monkeypatch.setattr(admin_service, "logger", logger)
    repo = Mock(fetch_is_admin=AsyncMock(side_effect=RuntimeError(marker)))
    settings = Mock(get_all=AsyncMock(side_effect=RuntimeError(marker)))
    cache = Mock(invalidate=AsyncMock(side_effect=RuntimeError(marker)))
    service = AdminService(repo, settings, cache)
    monkeypatch.setattr(service, "is_env_admin", lambda _: False)

    if operation == "profile":
        assert await service._invalidate_profile_cache("private-user", "private-email") is None
        cache.invalidate.assert_awaited_once()
    elif operation == "role":
        assert await service.is_admin("private-user") is False
        repo.fetch_is_admin.assert_awaited_once_with(user_id="private-user")
    else:
        view = await service.get_settings_view()
        assert view["settings"]
        assert all(not item["overridden"] for item in view["settings"])
    logger.debug.assert_called_once()
    args, kwargs = logger.debug.call_args
    assert len(args) == 1
    assert kwargs == {"extra": {"component": f"admin_{operation}", "failure_code": "unavailable"}}
    assert marker not in repr(logger.mock_calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["profile", "role", "settings"])
async def test_lookup_cancellation_propagates_without_logging(monkeypatch, operation):
    logger = Mock()
    monkeypatch.setattr(admin_service, "logger", logger)
    repo = Mock(fetch_is_admin=AsyncMock(side_effect=asyncio.CancelledError()))
    settings = Mock(get_all=AsyncMock(side_effect=asyncio.CancelledError()))
    cache = Mock(invalidate=AsyncMock(side_effect=asyncio.CancelledError()))
    service = AdminService(repo, settings, cache)
    monkeypatch.setattr(service, "is_env_admin", lambda _: False)
    with pytest.raises(asyncio.CancelledError):
        if operation == "profile":
            await service._invalidate_profile_cache("user", "email")
        elif operation == "role":
            await service.is_admin("user")
        else:
            await service.get_settings_view()
    logger.debug.assert_not_called()
    assert service._cache == {}


@pytest.mark.asyncio
async def test_real_log_record_has_no_exception_or_private_identifier(monkeypatch, caplog):
    marker = "private-admin-db-response-marker"
    # Application logging can disable propagation during earlier startup tests.
    # Capture this real logger directly, independent of suite-wide root handlers.
    monkeypatch.setattr(admin_service.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(admin_service.logger, "propagate", False)
    service = AdminService(Mock(fetch_is_admin=AsyncMock(side_effect=RuntimeError(marker))), Mock())
    monkeypatch.setattr(service, "is_env_admin", lambda _: False)
    with caplog.at_level(logging.DEBUG, logger=admin_service.logger.name):
        assert await service.is_admin("private-owner-marker") is False
    records = [record for record in caplog.records if record.name == admin_service.logger.name]
    assert len(records) == 1
    assert records[0].exc_info is None
    assert records[0].component == "admin_role"
    assert records[0].failure_code == "unavailable"
    assert marker not in caplog.text
    assert "private-owner-marker" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("cached_role", [False, True])
async def test_existing_stale_role_fallback_is_unchanged(monkeypatch, cached_role):
    service = AdminService(
        Mock(fetch_is_admin=AsyncMock(side_effect=RuntimeError("private"))), Mock()
    )
    monkeypatch.setattr(service, "is_env_admin", lambda _: False)
    service._cache["user"] = (cached_role, 0.0)
    assert await service.is_admin("user") is cached_role
    assert service._cache["user"][0] is cached_role
