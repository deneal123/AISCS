"""Recoverable scan claims; private source keys never belong in diagnostics.

The existing producer list is retained during migration. A Lua transfer adds
the stream entry before removing the list item, within one Redis operation.
Result publication and acknowledgement are fenced and atomic. Redis transport
errors are deliberately propagated to the worker's bounded error boundary.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from service.infrastructure.cache.manager import call_redis

SCAN_LEASE_MS = 120_000
SCAN_MAX_ATTEMPTS = 3

_PREPARE = """
local result = redis.pcall('XGROUP', 'CREATE', KEYS[1], ARGV[1], '0', 'MKSTREAM')
if type(result) == 'table' and result.err then
  if string.sub(result.err, 1, 9) ~= 'BUSYGROUP' then
    return redis.error_reply('scan_queue_unavailable')
  end
end
return 1
"""

_TRANSFER = """
local item = redis.call('LINDEX', KEYS[1], 0)
if not item then return false end
local id
if #item == 0 or #item > 4096 then
  id = redis.call('XADD', KEYS[2], '*', 'invalid_source', '1')
else
  local encoded = string.gsub(item, '.', function(char)
    return string.format('%02x', string.byte(char))
  end)
  id = redis.call('XADD', KEYS[2], '*', 'file_key_hex', encoded)
end
redis.call('LPOP', KEYS[1])
return id
"""

_RENEW = """
local pending = redis.call('XPENDING', KEYS[1], ARGV[1], ARGV[2], ARGV[2], 1)
if #pending ~= 1 or pending[1][2] ~= ARGV[3]
   or pending[1][4] ~= tonumber(ARGV[4])
   or pending[1][3] >= tonumber(ARGV[5]) then return 0 end
redis.call('XCLAIM', KEYS[1], ARGV[1], ARGV[3], 0, ARGV[2], 'JUSTID')
return 1
"""

_PUBLISH = """
local pending = redis.call('XPENDING', KEYS[1], ARGV[1], ARGV[2], ARGV[2], 1)
if #pending ~= 1 or pending[1][2] ~= ARGV[3]
   or pending[1][4] ~= tonumber(ARGV[4])
   or pending[1][3] >= tonumber(ARGV[5]) then return 0 end
-- XADD is first: a wrong-type/unavailable destination cannot acknowledge work.
if tonumber(ARGV[7]) > 0 then
  redis.call('XADD', KEYS[2], 'MAXLEN', '~', ARGV[7], '*', 'data', ARGV[6])
else
  redis.call('XADD', KEYS[2], '*', 'data', ARGV[6])
end
redis.call('XACK', KEYS[1], ARGV[1], ARGV[2])
redis.call('XDEL', KEYS[1], ARGV[2])
return 1
"""

_RETIRE = """
local pending = redis.call('XPENDING', KEYS[1], ARGV[1], '-', '+', 1, ARGV[2])
if #pending ~= 0 then return 0 end
redis.call('XGROUP', 'DELCONSUMER', KEYS[1], ARGV[1], ARGV[2])
return 1
"""


@dataclass(frozen=True, slots=True)
class ScanClaim:
    entry_id: str = field(repr=False)
    file_key: str | None = field(repr=False)
    consumer: str = field(repr=False)
    attempt: int

    @property
    def exhausted(self) -> bool:
        return self.attempt > SCAN_MAX_ATTEMPTS


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise ValueError("scan_claim_invalid")


def _source_key(fields: dict) -> str | None:
    """Decode bounded binary-safe migration; invalid items receive a terminal claim."""
    try:
        encoded = fields.get("file_key_hex", fields.get(b"file_key_hex"))
        if encoded is not None:
            encoded = _text(encoded)
            if len(encoded) > 8192:
                return None
            value = bytes.fromhex(encoded).decode("utf-8")
        else:
            value = _text(fields.get("file_key", fields.get(b"file_key")))
        if not value or len(value.encode("utf-8")) > 4096 or any(ord(c) < 32 for c in value):
            return None
        return value
    except (ValueError, UnicodeError):
        return None


class DurableScanQueue:
    """One worker consumer; server-owned pending idle time defines its lease.

    Keep this owner across polling iterations. No acknowledged entry is retried;
    an unavailable/uncertain publication stays pending until reclaim. A replaced
    owner or expired attempt cannot publish, renew or acknowledge newer work.
    """

    def __init__(self, redis_client: Any, *, namespace: str = "file:scan") -> None:
        self.redis = redis_client
        self.source = f"{namespace}:queue"
        self.stream = f"{namespace}:claims"
        self.group = "file-scanners-v1"
        self.failures = f"{namespace}:failures"
        self.consumer = uuid4().hex
        self._reclaim_cursor = "0-0"
        self._prepared = False
        self._polls = 0

    async def prepare(self) -> None:
        if not self._prepared:
            await call_redis(self.redis, "eval", _PREPARE, 1, self.stream, self.group)
            self._prepared = True

    async def transfer_one(self) -> str | None:
        """Migrate one legacy item without a pop-before-persist crash seam."""
        await self.prepare()
        result = await call_redis(self.redis, "eval", _TRANSFER, 2, self.source, self.stream)
        return _text(result) if result else None

    async def claim(self) -> ScanClaim | None:
        await self.prepare()
        if self._polls % 64 == 0:
            await self.retire_idle_consumers()
        self._polls += 1
        reclaimed = await call_redis(
            self.redis,
            "xautoclaim",
            self.stream,
            self.group,
            self.consumer,
            SCAN_LEASE_MS,
            start_id=self._reclaim_cursor,
            count=1,
        )
        self._reclaim_cursor = _text(reclaimed[0])
        entries = reclaimed[1]
        if not entries:
            await self.transfer_one()
            batches = await call_redis(
                self.redis, "xreadgroup", self.group, self.consumer, {self.stream: ">"}, count=1
            )
            entries = batches[0][1] if batches else []
        if not entries:
            return None
        entry_id, fields = entries[0]
        entry_id = _text(entry_id)
        file_key = _source_key(fields)
        pending = await call_redis(
            self.redis, "xpending_range", self.stream, self.group, entry_id, entry_id, 1
        )
        if not pending or _text(pending[0]["consumer"]) != self.consumer:
            return None
        attempt = pending[0]["times_delivered"]
        if type(attempt) is not int or attempt < 1:
            raise ValueError("scan_claim_invalid")
        return ScanClaim(entry_id, file_key, self.consumer, attempt)

    async def renew(self, claim: ScanClaim) -> bool:
        if claim.consumer != self.consumer:
            return False
        result = await call_redis(
            self.redis,
            "eval",
            _RENEW,
            1,
            self.stream,
            self.group,
            claim.entry_id,
            claim.consumer,
            claim.attempt,
            SCAN_LEASE_MS,
        )
        return result == 1

    async def publish(self, claim: ScanClaim, stream: str, payload: str) -> bool:
        if claim.consumer != self.consumer:
            return False
        result = await call_redis(
            self.redis,
            "eval",
            _PUBLISH,
            2,
            self.stream,
            stream,
            self.group,
            claim.entry_id,
            claim.consumer,
            claim.attempt,
            SCAN_LEASE_MS,
            payload,
            1000 if stream == self.failures else 0,
        )
        return result == 1

    async def retire_idle_consumers(self) -> None:
        """Prune at most sixteen retired owners; Lua rechecks pending ownership."""
        consumers = await call_redis(self.redis, "xinfo_consumers", self.stream, self.group)
        retired = 0
        for consumer in consumers:
            name = _text(consumer["name"])
            if (
                name == self.consumer
                or consumer["pending"] != 0
                or consumer["idle"] < SCAN_LEASE_MS
            ):
                continue
            await call_redis(self.redis, "eval", _RETIRE, 1, self.stream, self.group, name)
            retired += 1
            if retired >= 16:
                break

    async def close(self) -> None:
        if self._prepared:
            await call_redis(self.redis, "eval", _RETIRE, 1, self.stream, self.group, self.consumer)

    def invalidate(self) -> None:
        """Re-ensure the group after connection failure; preserve pending work."""
        self._prepared = False
