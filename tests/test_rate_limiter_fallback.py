"""In-memory фолбэк rate-limiter при недоступном Redis (аудит T2.5).

Раньше `redis is None` или сбой Redis → fail-open (пропускаем всех), что снимало защиту от
перебора пароля/OTP на auth-эндпоинтах во время Redis-outage. Теперь — локальный
(per-process) лимитер: слабее кросс-процессного, но без локаута легитимных.
"""

import pytest

from service.shared.security import rate_limiter as rl
from service.shared.security.rate_limiter import RateLimiter


@pytest.fixture(autouse=True)
def _clear_memory_buckets():
    rl._MEMORY_BUCKETS.clear()
    yield
    rl._MEMORY_BUCKETS.clear()


@pytest.mark.asyncio
async def test_memory_fallback_blocks_over_limit_without_redis():
    """redis=None: превышение лимита ДОЛЖНО блокироваться (раньше пропускалось)."""
    limiter = RateLimiter(None)
    limits = {"rpm": 3}
    now = 1000.0
    results = [await limiter.check(identity="ip1", limits=limits, now=now) for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False], "фолбэк не блокирует перебор"
    assert results[-1].scope == "rpm"
    assert results[-1].retry_after > 0


@pytest.mark.asyncio
async def test_memory_fallback_isolates_identities():
    limiter = RateLimiter(None)
    limits = {"rpm": 1}
    now = 1000.0
    assert (await limiter.check(identity="a", limits=limits, now=now)).allowed is True
    assert (await limiter.check(identity="a", limits=limits, now=now)).allowed is False
    # другой identity — свой счётчик
    assert (await limiter.check(identity="b", limits=limits, now=now)).allowed is True


@pytest.mark.asyncio
async def test_memory_fallback_new_window_resets():
    limiter = RateLimiter(None)
    limits = {"rpm": 1}
    assert (await limiter.check(identity="a", limits=limits, now=1000.0)).allowed is True
    assert (await limiter.check(identity="a", limits=limits, now=1000.0)).allowed is False
    # +60с → новое минутное окно → снова можно
    assert (await limiter.check(identity="a", limits=limits, now=1061.0)).allowed is True


@pytest.mark.asyncio
async def test_redis_error_falls_back_to_memory():
    """Сбой Redis-incr → не fail-open, а фолбэк в память (тоже блокирует перебор)."""

    class _BoomRedis:
        async def incr(self, key):
            raise RuntimeError("redis down")

        async def expire(self, key, window):
            pass

    limiter = RateLimiter(_BoomRedis())
    limits = {"rpm": 2}
    now = 5000.0
    allowed = [
        (await limiter.check(identity="x", limits=limits, now=now)).allowed for _ in range(3)
    ]
    assert allowed == [True, True, False], "при сбое Redis перебор не блокируется"


@pytest.mark.asyncio
async def test_no_identity_is_allowed():
    res = await RateLimiter(None).check(identity=None, limits={"rpm": 1}, now=1.0)
    assert res.allowed is True


def test_stale_bucket_eviction():
    """Протухшие бакеты вычищаются (не растут бесконечно)."""
    rl._MEMORY_BUCKETS[("old", "rpm", 0)] = 5  # окно [0;60) — протухло к now=1000
    rl._MEMORY_BUCKETS[("cur", "rpm", 16)] = 1  # окно [960;1020) — активно при now=1000
    rl._evict_stale_buckets(1000.0)
    assert ("old", "rpm", 0) not in rl._MEMORY_BUCKETS
    assert ("cur", "rpm", 16) in rl._MEMORY_BUCKETS
