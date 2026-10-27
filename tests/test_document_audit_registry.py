"""Producer completion is explicit; missing/old state does not authorize retries."""

import copy
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.infrastructure.document_audit import registry as registry_module
from service.infrastructure.document_audit.registry import (
    AuditProducerRegistry,
    AuditRegistryUnavailable,
)


class RedisFixture:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, *, nx, ex):
        assert nx and ex > 0
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def eval(self, script, count, key, expected, replacement, ttl):
        assert count == 1 and ttl > 0
        if self.values.get(key) != expected:
            return 0
        self.values[key] = replacement
        return 1


def store(redis, attempt=None, scope="a" * 64):
    return AuditProducerRegistry(redis, attempt_id=attempt or str(uuid4()), scope_digest=scope)


def checkpoint(registry):
    return {
        "schema_version": 1,
        "attempt_id": registry.attempt,
        "revision": 1,
        "receipts": [
            {
                "receipt_id": "fixture",
                "provider": "gigachat",
                "model": "GigaChat-2-Max",
                "kind": "document_visual_audit",
                "prompt": 30,
                "completion": 3,
                "estimated": True,
            }
        ],
    }


@pytest.mark.asyncio
async def test_new_reader_recovers_exact_checkpoint_and_explicit_terminal_without_token():
    redis = RedisFixture()
    producer = store(redis)
    assert await producer.claim(fresh_attempt=True)
    payload = checkpoint(producer)
    await producer.checkpoint(payload)
    reader = store(redis, producer.attempt)
    assert await reader.snapshot() == {"state": "active", "checkpoint": payload, "result": None}
    assert not await reader.claim(fresh_attempt=True)
    result = {"status": "failed", "passed": False, "retryable": False}
    await producer.seal(result)
    assert await reader.snapshot() == {"state": "terminal", "checkpoint": payload, "result": result}
    await producer.seal(result)  # Exact result replay does not mutate accounting.
    with pytest.raises(AuditRegistryUnavailable):
        await producer.checkpoint(payload)
    with pytest.raises(AuditRegistryUnavailable):
        await reader.seal(result)


@pytest.mark.asyncio
async def test_unknown_or_wrong_scope_cannot_authorize_recovery_execution():
    redis = RedisFixture()
    original = store(redis)
    assert await original.snapshot() == {"state": "unknown"}
    with pytest.raises(AuditRegistryUnavailable):
        await original.claim()
    assert await original.claim(fresh_attempt=True)
    with pytest.raises(AuditRegistryUnavailable):
        await store(redis, original.attempt, "b" * 64).snapshot()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["erase", "provenance", "counter", "raw_field", "unsafe_model"])
async def test_checkpoint_never_erases_or_contaminates_known_expense(fault):
    redis = RedisFixture()
    producer = store(redis)
    assert await producer.claim(fresh_attempt=True)
    original = checkpoint(producer)
    await producer.checkpoint(original)
    invalid = copy.deepcopy(original)
    invalid["revision"] = 2
    call = invalid["receipts"][0]
    if fault == "erase":
        invalid["receipts"] = []
    elif fault == "provenance":
        call["model"] = "GigaChat-2"
    elif fault == "counter":
        call["prompt"] = 99
    elif fault == "raw_field":
        call["provider_body"] = "private-marker"
    else:
        call["model"] = "https://private-marker.test"
    with pytest.raises(AuditRegistryUnavailable):
        await producer.checkpoint(invalid)
    assert (await producer.snapshot())["checkpoint"] == original


@pytest.mark.asyncio
async def test_exact_refinement_survives_compare_and_swap():
    redis = RedisFixture()
    producer = store(redis)
    assert await producer.claim(fresh_attempt=True)
    payload = checkpoint(producer)
    await producer.checkpoint(payload)
    refined = copy.deepcopy(payload)
    refined["revision"] = 2
    refined["receipts"][0].update(prompt=20, completion=2, estimated=False)
    await producer.checkpoint(refined)
    assert (await producer.snapshot())["checkpoint"] == refined
    redis.eval = AsyncMock(return_value=0)
    third = copy.deepcopy(refined)
    third["revision"] = 3
    with pytest.raises(AuditRegistryUnavailable):
        await producer.checkpoint(third)
    assert (await producer.snapshot())["checkpoint"] == refined


@pytest.mark.asyncio
async def test_missing_redis_or_transport_body_is_bounded():
    with pytest.raises(AuditRegistryUnavailable):
        await store(None).claim(fresh_attempt=True)
    redis = RedisFixture()
    redis.set = AsyncMock(side_effect=RuntimeError("private-redis-body-marker"))
    with pytest.raises(AuditRegistryUnavailable) as raised:
        await store(redis).claim(fresh_attempt=True)
    assert str(raised.value) == "document_audit_registry_unavailable"
    assert raised.value.__suppress_context__


@pytest.mark.asyncio
async def test_positive_seal_requires_recorded_vision_expense():
    redis = RedisFixture()
    producer = store(redis)
    assert await producer.claim(fresh_attempt=True)
    with pytest.raises(AuditRegistryUnavailable):
        await producer.seal({"status": "passed", "passed": True, "retryable": False})
    assert (await producer.snapshot())["state"] == "active"


@pytest.mark.asyncio
async def test_legacy_active_state_has_no_process_death_authority(monkeypatch):
    redis = RedisFixture()
    producer = store(redis)
    assert await producer.claim(fresh_attempt=True)
    raw = json.loads(redis.values[producer.key])
    raw["schema_version"] = 1
    del raw["owner"]
    redis.values[producer.key] = json.dumps(raw)
    monkeypatch.setattr(registry_module, "owner_stopped", lambda _: True)
    assert (await producer.snapshot())["state"] == "active"
    raw.update(state="terminal", result={"status": "failed", "passed": False, "retryable": False})
    redis.values[producer.key] = json.dumps(raw)
    assert (await producer.snapshot())["state"] == "terminal"


@pytest.mark.asyncio
async def test_copied_claim_token_does_not_authorize_a_different_process(monkeypatch):
    redis = RedisFixture()
    owner = {"namespace": "a" * 64, "pid": 123, "start": 10}
    monkeypatch.setattr(registry_module, "process_owner", lambda: owner)
    producer = store(redis)
    assert await producer.claim(fresh_attempt=True)
    monkeypatch.setattr(registry_module, "process_owner", lambda: {**owner, "pid": 124})
    with pytest.raises(AuditRegistryUnavailable):
        await producer.checkpoint(checkpoint(producer))
