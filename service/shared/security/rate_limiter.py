"""Лимитер частоты запросов на Redis (фиксированные окна).

Простая, дешёвая (INCR+EXPIRE) и устойчивая к сбоям защита от флуда: на каждое
окно (минута/час/сутки) держим счётчик в бакете now//window. Превышение любого
окна → запрет с Retry-After до конца самого «дальнего» окна.

При недоступном/сбойном Redis — НЕ fail-open, а IN-MEMORY фолбэк (per-process): раньше
падение Redis молча снимало лимиты, открывая перебор пароля/OTP на auth-эндпоинтах.
Локальный лимитер слабее кросс-процессного (у каждого воркера свой счётчик, эффективный
лимит ×N воркеров), но это защита во время outage без локаута легитимных (в отличие от
fail-closed). Когда Redis жив — работает он.
"""

from __future__ import annotations

from dataclasses import dataclass

# (имя лимита в конфиге, длительность окна в секундах)
_WINDOWS: tuple[tuple[str, int], ...] = (("rpm", 60), ("rph", 3600), ("rpd", 86400))
_WINDOW_SEC = dict(_WINDOWS)

# IN-MEMORY фолбэк-счётчики (process-global): (identity, name, bucket) -> count.
_MEMORY_BUCKETS: dict[tuple[str, str, int], int] = {}
# Backstop против роста при флуде уникальных identity: при превышении чистим протухшие.
_MEMORY_BUCKETS_MAX = 20000


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int = 0
    scope: str | None = None


def _evict_stale_buckets(now: float) -> None:
    """Убрать бакеты, чьё окно уже закончилось (bucket+1)*window <= now."""
    stale = [k for k in _MEMORY_BUCKETS if (k[2] + 1) * _WINDOW_SEC.get(k[1], 0) <= now]
    for k in stale:
        _MEMORY_BUCKETS.pop(k, None)


def _memory_check(identity: str, limits: dict[str, int], now: float) -> RateLimitResult:
    """Фолбэк-лимитер в памяти процесса (когда Redis недоступен)."""
    retry_after = 0
    blocked_scope: str | None = None
    for name, window in _WINDOWS:
        limit = int(limits.get(name, 0) or 0)
        if limit <= 0:
            continue
        bucket = int(now // window)
        key = (identity, name, bucket)
        count = _MEMORY_BUCKETS.get(key, 0) + 1
        _MEMORY_BUCKETS[key] = count
        if count > limit:
            remaining = window - int(now % window)
            if remaining > retry_after:
                retry_after = remaining
                blocked_scope = name

    if len(_MEMORY_BUCKETS) > _MEMORY_BUCKETS_MAX:
        _evict_stale_buckets(now)

    if blocked_scope is not None:
        return RateLimitResult(allowed=False, retry_after=retry_after, scope=blocked_scope)
    return RateLimitResult(allowed=True)


class RateLimiter:
    def __init__(self, redis_client, *, key_prefix: str = "ratelimit") -> None:
        self._redis = redis_client
        self._prefix = key_prefix

    async def check(
        self, *, identity: str | None, limits: dict[str, int], now: float
    ) -> RateLimitResult:
        if not identity:
            return RateLimitResult(allowed=True)
        if self._redis is None:
            # Redis не сконфигурирован — лимитируем в памяти, а не пропускаем всех.
            return _memory_check(identity, limits, now)

        retry_after = 0
        blocked_scope: str | None = None
        for name, window in _WINDOWS:
            limit = int(limits.get(name, 0) or 0)
            if limit <= 0:
                continue
            bucket = int(now // window)
            key = f"{self._prefix}:{identity}:{name}:{bucket}"
            try:
                count = int(await self._redis.incr(key))
                if count == 1:
                    await self._redis.expire(key, window)
            except Exception:
                # Сбой Redis — не fail-open, а in-memory фолбэк (защита во время outage).
                return _memory_check(identity, limits, now)
            if count > limit:
                remaining = window - int(now % window)
                if remaining > retry_after:
                    retry_after = remaining
                    blocked_scope = name

        if blocked_scope is not None:
            return RateLimitResult(allowed=False, retry_after=retry_after, scope=blocked_scope)
        return RateLimitResult(allowed=True)
