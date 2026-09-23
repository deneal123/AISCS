"""Счётчик визитов /public дедупится по посетителю (аудит T4).

Раньше инкремент шёл на КАЖДЫЙ хит — F5 в цикле накручивал любое число. Теперь +1 раз в
сутки на посетителя (дедуп по хэшу IP через Redis SET NX EX).
"""

import pytest

from service.services.analytics.application import public_stats as ps


class _FakeRedis:
    def __init__(self):
        self.kv = {}
        self.counter = 0

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def incr(self, key):
        self.counter += 1
        self.kv[key] = self.counter
        return self.counter

    async def get(self, key):
        return self.kv.get(key)

    async def delete(self, *keys):
        for k in keys:
            self.kv.pop(k, None)


@pytest.fixture
def _fake_redis(monkeypatch):
    fake = _FakeRedis()

    class _Mgr:
        def __init__(self, cfg):
            pass

        def get_client(self):
            return fake

    monkeypatch.setattr(ps, "RedisManager", _Mgr)
    return fake


@pytest.mark.asyncio
async def test_same_visitor_counts_once(_fake_redis):
    for _ in range(5):
        await ps._visits(True, "visitorA")
    assert await ps._visits(False, None) == 1, "5 хитов одного посетителя должны дать +1"


@pytest.mark.asyncio
async def test_distinct_visitors_each_count(_fake_redis):
    await ps._visits(True, "A")
    await ps._visits(True, "B")
    await ps._visits(True, "A")  # повтор A не считается
    assert await ps._visits(False, None) == 2


@pytest.mark.asyncio
async def test_no_visitor_id_does_not_increment(_fake_redis):
    await ps._visits(True, None)
    assert await ps._visits(False, None) == 0, "без visitor_id только читаем, не крутим"
