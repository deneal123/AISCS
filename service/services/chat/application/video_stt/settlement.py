"""Content-free pending STT charges; independent of the originating job lease.

Cache and financial envelope are written atomically. Transcript cache expires;
the bounded envelope does not expire before an idempotent DB settlement.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any
from uuid import UUID

from service.infrastructure.cache.manager import call_redis
from service.models.key_value import ServiceType

INDEX = "video:stt:pending-charges"
SAVE_PENDING = """
redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[3])
redis.call('set', KEYS[2], ARGV[2])
redis.call('zadd', KEYS[3], ARGV[4], KEYS[2])
return 1
"""
COMPLETE = """
local raw = redis.call('get', KEYS[1])
if raw then
    local valid, state = pcall(cjson.decode, raw)
    if valid then
        state['status'] = 'completed'
        redis.call('set', KEYS[1], cjson.encode(state), 'KEEPTTL')
    end
end
redis.call('del', KEYS[2])
redis.call('zrem', KEYS[3], KEYS[2])
return 1
"""


def journal_key(owner_id: str, job_id: str) -> str:
    digest = hashlib.sha256(
        json.dumps([owner_id, job_id], separators=(",", ":")).encode()
    ).hexdigest()
    return f"video:stt:{digest}"


def charge_key(key: str) -> str:
    return key.replace("video:stt:", "video:stt:charge:", 1)


async def save_pending(redis: Any, key: str, state: dict[str, Any], ttl: int) -> None:
    envelope = {
        field: state[field]
        for field in (
            "owner_id",
            "job_id",
            "reservation_id",
            "model",
            "duration_sec",
            "credits",
            "raw_cost_rub",
        )
    }
    envelope["journal_key"] = key
    await call_redis(
        redis,
        "eval",
        SAVE_PENDING,
        3,
        key,
        charge_key(key),
        INDEX,
        json.dumps(state, separators=(",", ":")),
        json.dumps(envelope, separators=(",", ":")),
        ttl,
        time.time(),
    )


async def commit_charge(redis: Any, billing: Any, key: str, envelope: dict[str, Any]) -> None:
    await billing.charge(
        envelope["owner_id"],
        credits=envelope["credits"],
        tokens=0,
        raw_cost_rub=envelope["raw_cost_rub"],
        reservation_id=envelope["reservation_id"],
        idempotency_key=key,
        metadata={
            "kind": "transcription",
            "engine": "local",
            "model": envelope["model"],
            "duration_sec": envelope["duration_sec"],
            "duration_estimated": False,
        },
    )
    await call_redis(redis, "eval", COMPLETE, 3, key, charge_key(key), INDEX)


def valid_envelope(value: Any, pending_key: str) -> bool:
    try:
        key = journal_key(str(UUID(value["owner_id"])), str(UUID(value["job_id"])))
        return (
            value["journal_key"] == key
            and charge_key(key) == pending_key
            and type(value["credits"]) is int
            and value["credits"] >= 0
            and isinstance(value["raw_cost_rub"], (int, float))
            and not isinstance(value["raw_cost_rub"], bool)
            and math.isfinite(value["raw_cost_rub"])
            and value["raw_cost_rub"] >= 0
            and isinstance(value["duration_sec"], (int, float))
            and not isinstance(value["duration_sec"], bool)
            and math.isfinite(value["duration_sec"])
            and 0 < value["duration_sec"] <= 7200
            and isinstance(value["model"], str)
            and 0 < len(value["model"]) <= 64
            and isinstance(value["reservation_id"], str)
            and bool(value["reservation_id"])
        )
    except (ValueError, KeyError, TypeError):
        return False


async def reconcile_pending_video_stt(redis: Any, billing: Any, jobs: Any) -> dict[str, int]:
    """One bounded scan, no inference or transcription; terminal jobs may settle."""
    counts = {"examined": 0, "settled": 0, "deferred": 0, "invalid": 0}
    keys = await call_redis(redis, "zrange", INDEX, 0, 63)
    for raw_key in keys:
        counts["examined"] += 1
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        try:
            raw = await call_redis(redis, "get", key)
            if raw is None:
                await call_redis(redis, "zrem", INDEX, key)
                continue
            envelope = json.loads(raw)
            if not valid_envelope(envelope, key):
                counts["invalid"] += 1
                await call_redis(redis, "zadd", INDEX, {key: time.time()})
                continue
            job = await jobs.fetch_job_by_id(UUID(envelope["job_id"]), UUID(envelope["owner_id"]))
            if job is None or job.type != ServiceType.CHAT:
                counts["invalid"] += 1
                await call_redis(redis, "zadd", INDEX, {key: time.time()})
                continue
            await commit_charge(redis, billing, envelope["journal_key"], envelope)
            counts["settled"] += 1
        except Exception:
            counts["deferred"] += 1
            await call_redis(redis, "zadd", INDEX, {key: time.time()})
    return counts
