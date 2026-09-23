"""Фаза 5: лимитер частоты (Redis fixed-window) + WS-гейт анти-флуда."""

import pytest

from service.shared.security.rate_limiter import RateLimiter, RateLimitResult


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.expires = {}

    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key, ttl):
        self.expires[key] = ttl


@pytest.mark.asyncio
async def test_rate_limiter_allows_then_blocks_with_retry_after():
    rl = RateLimiter(_FakeRedis())
    limits = {"rpm": 3}
    for _ in range(3):
        assert (await rl.check(identity="u1", limits=limits, now=1000.0)).allowed
    blocked = await rl.check(identity="u1", limits=limits, now=1000.0)
    assert blocked.allowed is False
    assert blocked.scope == "rpm"
    assert blocked.retry_after == 20  # 60 - (1000 % 60)


@pytest.mark.asyncio
async def test_rate_limiter_separate_identities():
    rl = RateLimiter(_FakeRedis())
    limits = {"rpm": 1}
    assert (await rl.check(identity="a", limits=limits, now=1.0)).allowed
    assert (await rl.check(identity="b", limits=limits, now=1.0)).allowed  # другой юзер
    assert (await rl.check(identity="a", limits=limits, now=1.0)).allowed is False


@pytest.mark.asyncio
async def test_rate_limiter_fail_open_no_redis_or_identity():
    assert (await RateLimiter(None).check(identity="u1", limits={"rpm": 1}, now=1.0)).allowed
    rl = RateLimiter(_FakeRedis())
    assert (await rl.check(identity=None, limits={"rpm": 1}, now=1.0)).allowed


@pytest.mark.asyncio
async def test_rate_limiter_falls_back_to_memory_on_redis_error():
    """Сбой Redis → НЕ fail-open, а in-memory фолбэк (аудит T2.5): первый запрос под лимитом
    проходит, но превышение блокируется (раньше падение Redis снимало лимит вовсе)."""

    class _Boom:
        async def incr(self, key):
            raise RuntimeError("redis down")

        async def expire(self, key, ttl):
            pass

    limiter = _Boom()
    first = await RateLimiter(limiter).check(identity="u1", limits={"rpm": 1}, now=1.0)
    second = await RateLimiter(limiter).check(identity="u1", limits={"rpm": 1}, now=1.0)
    assert first.allowed is True, "первый запрос под лимитом проходит"
    assert second.allowed is False, "превышение при сбое Redis должно блокироваться (не fail-open)"


# --- WS-гейт ---------------------------------------------------------------- #
class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class _BlockingLimiter:
    async def check(self, *, identity, limits, now):
        return RateLimitResult(allowed=False, retry_after=30, scope="rpm")


class _AllowLimiter:
    async def check(self, *, identity, limits, now):
        return RateLimitResult(allowed=True)


@pytest.mark.asyncio
async def test_ws_handler_blocks_when_rate_limited():
    from service.services.chat.presentation.ws.chat_ws.message_handler import ChatMessageHandler

    handler = ChatMessageHandler(
        None, None, object(), None, rate_limiter=_BlockingLimiter(), rate_limits={"rpm": 1}
    )
    ws = _FakeWS()
    blocked = await handler._is_rate_limited(ws, {"id": "m1"}, {"user_id": "u1"})
    assert blocked is True
    assert ws.sent[0]["code"] == "rate_limited"
    assert ws.sent[0]["retry_after"] == 30


@pytest.mark.asyncio
async def test_ws_handler_allows_when_under_limit():
    from service.services.chat.presentation.ws.chat_ws.message_handler import ChatMessageHandler

    handler = ChatMessageHandler(
        None, None, object(), None, rate_limiter=_AllowLimiter(), rate_limits={"rpm": 1}
    )
    ws = _FakeWS()
    assert await handler._is_rate_limited(ws, {"id": "m1"}, {"user_id": "u1"}) is False
    assert ws.sent == []


@pytest.mark.asyncio
async def test_ws_handler_no_limiter_allows():
    from service.services.chat.presentation.ws.chat_ws.message_handler import ChatMessageHandler

    handler = ChatMessageHandler(None, None, object(), None)
    assert await handler._is_rate_limited(_FakeWS(), {}, {"user_id": "u1"}) is False
