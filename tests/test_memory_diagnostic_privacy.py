"""Memory diagnostics must not carry identities, paths or integration exceptions."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from service.infrastructure.memory.base import NoopMemoryIntegration
from service.infrastructure.memory.memos import MemOSMemoryIntegration
from service.services.analytics.application.memory import cache as memory_cache
from service.services.analytics.application.memory import service as memory_service


def capture(monkeypatch, caplog, logger):
    monkeypatch.setattr(logger, "disabled", False)
    monkeypatch.setattr(logger, "propagate", False)
    monkeypatch.setattr(logger, "handlers", [caplog.handler])
    monkeypatch.setattr(logger, "level", logging.DEBUG)


@pytest.mark.asyncio
async def test_cache_fallbacks_never_log_redis_exception_or_cached_content(monkeypatch, caplog):
    from service.infrastructure.cache import manager as redis_manager

    marker = "private-memory-cache-marker"
    capture(monkeypatch, caplog, memory_cache.logger)
    monkeypatch.setattr(redis_manager, "RedisManager", Mock(side_effect=RuntimeError(marker)))
    assert memory_cache._redis() is None
    client = SimpleNamespace(
        get=AsyncMock(side_effect=RuntimeError(marker)),
        set=AsyncMock(side_effect=RuntimeError(marker)),
        delete=AsyncMock(side_effect=RuntimeError(marker)),
    )
    monkeypatch.setattr(memory_cache, "_redis", lambda: client)
    assert await memory_cache.get(marker) is None
    await memory_cache.put(marker, {marker: marker})
    await memory_cache.invalidate(marker)
    assert [record.operation for record in caplog.records] == [
        "connect",
        "read",
        "write",
        "invalidate",
    ]
    assert all(
        record.exc_info is None and marker not in str(record.__dict__) for record in caplog.records
    )


@pytest.mark.parametrize("stage", ["start", "success", "failure"])
def test_integration_diagnostics_project_only_bounded_values(monkeypatch, caplog, stage):
    integration = NoopMemoryIntegration()
    capture(monkeypatch, caplog, integration.logger)
    marker = "private-memory-marker"
    if stage == "start":
        integration._log_operation_start(marker, user_id=marker, fact_id=marker, facts=3)
    elif stage == "success":
        integration._log_operation_success(marker, 0, path=marker, content=marker, facts=3)
    else:
        integration._log_operation_failure(marker, 0, RuntimeError(marker))
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert marker not in str(record.__dict__)
    assert record.component == "memory"
    assert record.operation == "other"
    assert record.exc_info is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["wipe", "forget_user"])
async def test_memos_transport_failure_has_bounded_result_and_logs(monkeypatch, caplog, action):
    def failed(request):
        raise httpx.ConnectError("private-memory-marker")

    integration = MemOSMemoryIntegration(
        base_url="http://memory.invalid", transport=httpx.MockTransport(failed)
    )
    capture(monkeypatch, caplog, integration.logger)
    result = (
        await integration.wipe()
        if action == "wipe"
        else await integration.forget_user(user_id="private-owner-marker")
    )
    assert result == {"ok": False, "error": "transport"}
    assert "private-memory-marker" not in str([record.__dict__ for record in caplog.records])
    assert "private-owner-marker" not in str([record.__dict__ for record in caplog.records])
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_service_wipe_failure_does_not_expose_class_or_trace(monkeypatch, caplog):
    private_error = type("PrivateMemoryMarker", (RuntimeError,), {})

    class FailedStore:
        async def delete_all_facts(self, **kwargs):
            raise private_error("private-memory-marker")

        async def forget_user(self, **kwargs):
            raise private_error("private-memory-marker")

    async def invalidate(_owner):
        return None

    monkeypatch.setattr(memory_cache, "invalidate", invalidate)
    capture(monkeypatch, caplog, memory_service.logger)
    result = await memory_service.MemoryService(
        integration=FailedStore(), facts_repo=FailedStore()
    ).forget_everything("private-owner-marker")
    assert result == {
        "facts_deleted": 0,
        "facts_error": "unavailable",
        "memos": {"ok": False, "error": "unavailable"},
    }
    assert len(caplog.records) == 2
    assert "PrivateMemoryMarker" not in str(result)
    assert "private-memory-marker" not in str([record.__dict__ for record in caplog.records])
    assert all(record.exc_info is None for record in caplog.records)
