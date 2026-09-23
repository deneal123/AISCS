"""Фаза 5: детекция аномальной скорости трат + запись флага."""

import json

import pytest

from service.services.billing.application.abuse import accumulate_spend
from service.services.billing.persistence.billing_repository import BillingRepository
from tests.test_helpers import FakeConnector, FakeDBSession


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.expires = {}

    async def incrby(self, key, amount):
        self.store[key] = self.store.get(key, 0) + amount
        return self.store[key]

    async def expire(self, key, ttl):
        self.expires[key] = ttl


@pytest.mark.asyncio
async def test_accumulate_spend_accumulates_in_window():
    redis = _FakeRedis()
    first = await accumulate_spend(
        redis, user_id="u1", credits=100, window_seconds=3600, now=1000.0
    )
    second = await accumulate_spend(
        redis, user_id="u1", credits=50, window_seconds=3600, now=1500.0
    )
    assert first == 100
    assert second == 150
    # TTL выставлен один раз при первой записи окна
    assert list(redis.expires.values()) == [3600]


@pytest.mark.asyncio
async def test_accumulate_spend_fail_open():
    assert (
        await accumulate_spend(None, user_id="u1", credits=10, window_seconds=3600, now=1.0) is None
    )
    redis = _FakeRedis()
    assert (
        await accumulate_spend(redis, user_id="u1", credits=0, window_seconds=3600, now=1.0) is None
    )
    assert (
        await accumulate_spend(redis, user_id="", credits=10, window_seconds=3600, now=1.0) is None
    )


@pytest.mark.asyncio
async def test_record_flag_writes_event():
    session = FakeDBSession()
    repo = BillingRepository(FakeConnector(session))
    await repo.record_flag(
        user_id="11111111-1111-1111-1111-111111111111",
        event_type="abuse_flag",
        metadata={"spent_window": 999999, "window_sec": 3600},
    )
    assert len(session.executed) == 1
    sql, params = session.executed[0]
    assert "INSERT INTO profile.billing_events" in sql
    assert params["event_type"] == "abuse_flag"
    assert json.loads(params["metadata"])["spent_window"] == 999999
    assert session._committed is True
