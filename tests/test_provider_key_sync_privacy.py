"""An unavailable secret store is not an authoritative empty key snapshot."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from service.infrastructure.agents_client import engine_factory, sidecar_providers
from service.services.admin.application import provider_key_service as keys


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, ValueError])
async def test_failed_secret_read_does_not_clear_sidecar_keys(monkeypatch, failure):
    logger = Mock()
    monkeypatch.setattr(keys, "logger", logger)
    monkeypatch.setattr(engine_factory, "uses_http_engine", lambda _: True)
    monkeypatch.setattr(sidecar_providers, "fetch_keys_version", AsyncMock(return_value=1))
    push = AsyncMock(return_value=True)
    monkeypatch.setattr(sidecar_providers, "push_provider_keys", push)
    service = keys.ProviderKeyService(
        Mock(get_all=AsyncMock(side_effect=failure("private-secret-store-marker")))
    )

    assert await service.ensure_sidecar_keys(version=2) is False
    push.assert_not_awaited()
    logger.warning.assert_called_once_with(
        "provider key snapshot unavailable",
        extra={"component": "provider_keys", "failure_code": "unavailable"},
    )
    assert "private-secret-store-marker" not in repr(logger.mock_calls)


@pytest.mark.asyncio
async def test_successful_empty_secret_snapshot_can_clear_overrides(monkeypatch):
    monkeypatch.setattr(engine_factory, "uses_http_engine", lambda _: True)
    monkeypatch.setattr(sidecar_providers, "fetch_keys_version", AsyncMock(return_value=1))
    push = AsyncMock(return_value=True)
    monkeypatch.setattr(sidecar_providers, "push_provider_keys", push)
    service = keys.ProviderKeyService(Mock(get_all=AsyncMock(return_value={})))
    assert await service.ensure_sidecar_keys(version=2) is True
    push.assert_awaited_once_with(keys.config, version=2, overrides={})


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["read", "decrypt"])
async def test_cancelled_snapshot_does_not_push_partial_keys(monkeypatch, stage):
    monkeypatch.setattr(engine_factory, "uses_http_engine", lambda _: True)
    monkeypatch.setattr(sidecar_providers, "fetch_keys_version", AsyncMock(return_value=1))
    push = AsyncMock(return_value=True)
    monkeypatch.setattr(sidecar_providers, "push_provider_keys", push)
    read = AsyncMock(return_value={"gigachat": {"secret_enc": "private"}})
    if stage == "read":
        read.side_effect = asyncio.CancelledError()
    else:
        monkeypatch.setattr(keys, "decrypt_secret", Mock(side_effect=asyncio.CancelledError()))
    service = keys.ProviderKeyService(Mock(get_all=read))
    with pytest.raises(asyncio.CancelledError):
        await service.ensure_sidecar_keys(version=2)
    push.assert_not_awaited()


@pytest.mark.asyncio
async def test_decrypt_failure_never_publishes_partial_snapshot(monkeypatch):
    monkeypatch.setattr(engine_factory, "uses_http_engine", lambda _: True)
    monkeypatch.setattr(sidecar_providers, "fetch_keys_version", AsyncMock(return_value=1))
    monkeypatch.setattr(
        keys, "decrypt_secret", Mock(side_effect=["private", ValueError("private")])
    )
    push = AsyncMock(return_value=True)
    monkeypatch.setattr(sidecar_providers, "push_provider_keys", push)
    service = keys.ProviderKeyService(
        Mock(
            get_all=AsyncMock(
                return_value={"openai": {"secret_enc": "a"}, "gigachat": {"secret_enc": "b"}}
            )
        )
    )
    assert await service.ensure_sidecar_keys(version=2) is False
    push.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["read", "bump", "hydrate"])
async def test_soft_key_failure_diagnostics_have_no_traceback(monkeypatch, operation):
    logger = Mock()
    monkeypatch.setattr(keys, "logger", logger)
    service = keys.ProviderKeyService(
        Mock(get_all=AsyncMock(side_effect=RuntimeError("private-key-marker")))
    )
    if operation == "read":
        assert await service._safe_get_all() == {}
    elif operation == "bump":
        monkeypatch.setattr(service, "_redis", Mock(side_effect=RuntimeError("private-key-marker")))
        await service._bump_version()
    else:
        monkeypatch.setattr(keys, "_applied_version", -1)
        monkeypatch.setattr(service, "_redis", lambda: Mock(get=AsyncMock(return_value=b"2")))
        monkeypatch.setattr(service, "ensure_sidecar_keys", AsyncMock(return_value=False))
        monkeypatch.setattr(service, "hydrate_all", AsyncMock(side_effect=RuntimeError("private")))
        assert await service.sync_if_changed() is False
        assert keys._applied_version == -1
    logger.debug.assert_called_once()
    assert logger.debug.call_args.kwargs == {
        "extra": {"component": "provider_keys", "failure_code": "unavailable"}
    }
