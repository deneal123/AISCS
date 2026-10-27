"""Corrupt cache data is a safe miss, never a key/body diagnostic."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.infrastructure.cache import cache as redis_cache


@pytest.fixture
def capture(monkeypatch, caplog):
    monkeypatch.setattr(redis_cache.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(redis_cache.logger, "propagate", False)
    caplog.set_level(logging.DEBUG, logger=redis_cache.logger.name)
    return caplog


def cache(raw):
    client = SimpleNamespace(get=AsyncMock(return_value=raw), delete=AsyncMock())
    service = redis_cache.RedisCacheService(client, SimpleNamespace(cache_prefix="PRIVATE_PREFIX"))
    return service, client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw", ["{PRIVATE_PAYLOAD", b"\xffPRIVATE_PAYLOAD", "[]", "null", "17", '"PRIVATE_PAYLOAD"']
)
async def test_corrupt_record_is_purged_without_logging_identifiers_or_body(capture, raw):
    service, client = cache(raw)
    assert await service.get_json("PRIVATE_NAMESPACE", "PRIVATE_EMAIL") is None
    client.delete.assert_awaited_once_with("PRIVATE_PREFIX:PRIVATE_NAMESPACE:PRIVATE_EMAIL")
    assert "PRIVATE" not in capture.text
    assert len(capture.records) == 1
    record = capture.records[0]
    assert record.component == "redis_cache"
    assert record.failure_code == "invalid"
    assert record.exc_info is None
    assert not record.args


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, "{}", b'{"count":2}'])
async def test_valid_object_and_absent_record_remain_unchanged(capture, raw):
    service, client = cache(raw)
    expected = None if raw is None else ({} if raw == "{}" else {"count": 2})
    assert await service.get_json("namespace", "identifier") == expected
    client.delete.assert_not_awaited()
    assert not capture.records


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["get", "delete"])
async def test_transport_failure_is_not_silently_converted_to_miss(capture, phase):
    service, client = cache("{PRIVATE_PAYLOAD")
    getattr(client, phase).side_effect = OSError("PRIVATE_TRANSPORT_BODY")
    with pytest.raises(OSError):
        await service.get_json("namespace", "identifier")
    assert "PRIVATE" not in capture.text
    assert all(record.exc_info is None for record in capture.records)


@pytest.mark.asyncio
async def test_cancelled_read_propagates_without_deletion_or_diagnostics(capture):
    service, client = cache("{}")
    client.get.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.get_json("namespace", "identifier")
    client.delete.assert_not_awaited()
    assert not capture.records
