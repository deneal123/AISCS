"""Startup, shutdown and compatibility health must not serialize integration errors."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from service.infrastructure import provider_policy_store
from service.services.admin.application.provider_key_service import ProviderKeyService
from service.utils import app_lifespan

MARKER = "PRIVATE-DSN-provider-body"


@pytest.fixture
def boundary(monkeypatch):
    connector = SimpleNamespace(verify_connection=AsyncMock(), close=AsyncMock())
    manager = SimpleNamespace(
        start=AsyncMock(),
        stop=AsyncMock(),
        start_task_with_restart=AsyncMock(),
    )
    container = SimpleNamespace(
        infra=SimpleNamespace(pg_connector=connector, background_task_manager=manager),
        services=SimpleNamespace(
            new_job_processor=SimpleNamespace(process_new_jobs=AsyncMock()),
            admin_service=SimpleNamespace(prime_provider_health=AsyncMock()),
        ),
    )
    logger = Mock()
    monkeypatch.setattr(app_lifespan, "logger", logger)
    monkeypatch.setattr(app_lifespan, "set_current_container", Mock())
    monkeypatch.setattr(app_lifespan, "get_current_container", lambda: container)
    hydrate = AsyncMock(return_value=0)
    prime = AsyncMock()
    monkeypatch.setattr(ProviderKeyService, "hydrate_all", hydrate)
    monkeypatch.setattr(provider_policy_store, "prime", prime)
    app = FastAPI()
    app.state.container = container
    return SimpleNamespace(
        app=app,
        container=container,
        connector=connector,
        manager=manager,
        hydrate=hydrate,
        prime=prime,
        logger=logger,
    )


def assert_safe(logger):
    assert MARKER not in repr(logger.mock_calls)
    assert all(not call.kwargs.get("exc_info") for call in logger.mock_calls)


@pytest.mark.asyncio
async def test_simulation_profile_uses_injected_container_without_starting_chat_loops(
    boundary, monkeypatch
):
    monkeypatch.setattr(
        app_lifespan,
        "Config",
        lambda: SimpleNamespace(service=SimpleNamespace(application_profile="simulation")),
    )
    async with app_lifespan.lifespan(boundary.app):
        pass
    boundary.connector.verify_connection.assert_awaited_once()
    boundary.manager.start.assert_not_awaited()
    boundary.hydrate.assert_not_awaited()
    boundary.manager.stop.assert_awaited_once()
    boundary.connector.close.assert_awaited_once()
    assert_safe(boundary.logger)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["hydrate", "policy", "health_schedule"])
async def test_soft_startup_failures_keep_service_alive_without_raw_errors(boundary, stage):
    if stage == "hydrate":
        boundary.hydrate.side_effect = RuntimeError(MARKER)
    elif stage == "policy":
        boundary.prime.side_effect = RuntimeError(MARKER)
    else:
        boundary.container.services.admin_service.prime_provider_health = Mock(
            side_effect=RuntimeError(MARKER)
        )
    async with app_lifespan.lifespan(boundary.app):
        pass
    boundary.manager.stop.assert_awaited_once()
    boundary.connector.close.assert_awaited_once()
    assert_safe(boundary.logger)


@pytest.mark.asyncio
async def test_fatal_startup_failure_is_bounded_and_cleanup_still_runs(boundary):
    boundary.connector.verify_connection.side_effect = RuntimeError(MARKER)
    with pytest.raises(RuntimeError, match="^startup_unavailable$") as failure:
        async with app_lifespan.lifespan(boundary.app):
            pytest.fail("invalid startup accepted")
    assert failure.value.__suppress_context__
    boundary.connector.close.assert_awaited_once()
    assert_safe(boundary.logger)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["task_manager", "database"])
async def test_shutdown_failure_does_not_log_raw_error(boundary, stage):
    failing = boundary.manager.stop if stage == "task_manager" else boundary.connector.close
    failing.side_effect = RuntimeError(MARKER)
    async with app_lifespan.lifespan(boundary.app):
        pass
    boundary.connector.close.assert_awaited_once()
    assert_safe(boundary.logger)


@pytest.mark.asyncio
async def test_compatibility_health_failure_is_bounded(boundary):
    boundary.connector.verify_connection.side_effect = RuntimeError(MARKER)
    result = await app_lifespan.health_check()
    assert result == {"status": "unhealthy", "error": "unavailable", "version": "1.0.0"}
    assert_safe(boundary.logger)
