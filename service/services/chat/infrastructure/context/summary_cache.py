"""Версионированный кэш резюме и единственный владелец его публикации."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from service.infrastructure.cache.manager import call_redis

TTL = 7 * 24 * 3600
LEASE_SECONDS = 90
PUBLISH = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
redis.call('DEL', KEYS[1])
return 1
"""
RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


def summary_key(cache_prefix: str, session_id: str) -> str:
    return f"{(cache_prefix or 'gpthub').rstrip(':')}:agents:summary:{session_id}"


def fingerprints(items: list[dict]) -> list[str]:
    return [
        hashlib.sha256(
            json.dumps(
                {"role": item.get("role"), "content": item.get("content")},
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        for item in items
    ]


async def read(client: Any, key: str) -> dict:
    raw = await call_redis(client, "get", key)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError, UnicodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def reusable(cached: dict, source: list[str], max_tokens: int) -> bool:
    return (
        isinstance(cached.get("summary"), str)
        and bool(cached["summary"].strip())
        and (
            cached.get("version") == 2
            and cached.get("source") == source
            and cached.get("max_tokens") == max_tokens
        )
    )


def incremental_messages(cached: dict, source: list[str], older: list[dict]) -> list[dict]:
    previous = cached.get("source")
    if cached.get("version") != 2 or not isinstance(previous, list) or not cached.get("summary"):
        return older
    # Совпадение подтверждается содержимым, не длиной скользящего окна.
    for size in range(min(len(previous), len(source)), 0, -1):
        if previous[-size:] == source[:size]:
            return [
                {
                    "role": "assistant",
                    "content": (
                        "Предыдущее резюме более ранней истории (не новая реплика пользователя):\n"
                        + cached["summary"]
                    ),
                },
                *older[size:],
            ]
    return older
