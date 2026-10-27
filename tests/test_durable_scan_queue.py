"""Scan claim fencing and private queue protocol contracts."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.files.infrastructure.scan_queue import (
    SCAN_LEASE_MS,
    DurableScanQueue,
    ScanClaim,
    _source_key,
)


@pytest.mark.asyncio
async def test_prepare_is_once_and_transfer_keeps_legacy_list_contract():
    redis = SimpleNamespace(eval=AsyncMock(side_effect=[1, b"1-0", None]))
    queue = DurableScanQueue(redis)
    assert await queue.transfer_one() == "1-0"
    assert await queue.transfer_one() is None
    assert redis.eval.await_count == 3
    transfer = redis.eval.await_args_list[1].args
    assert transfer[1:] == (2, "file:scan:queue", "file:scan:claims")
    assert transfer[0].index("'XADD'") < transfer[0].index("'LPOP'")


@pytest.mark.asyncio
@pytest.mark.parametrize("reclaimed", [False, True])
async def test_claim_uses_actual_pending_owner_and_delivery_count(reclaimed):
    redis = SimpleNamespace(
        eval=AsyncMock(return_value=1),
        xinfo_consumers=AsyncMock(return_value=[]),
        xautoclaim=AsyncMock(return_value=[b"0-0", []]),
        xreadgroup=AsyncMock(return_value=[]),
        xpending_range=AsyncMock(),
    )
    queue = DurableScanQueue(redis)
    entry = (b"1-0", {b"file_key": b"private-scan-key"})
    if reclaimed:
        redis.xautoclaim.return_value = [b"3-0", [entry]]
    else:
        redis.eval.side_effect = [1, None]
        redis.xreadgroup.return_value = [(b"stream", [entry])]
    redis.xpending_range.return_value = [{"consumer": queue.consumer, "times_delivered": 2}]
    claim = await queue.claim()
    assert claim.file_key == "private-scan-key" and claim.attempt == 2
    assert "private-scan-key" not in repr(claim)
    assert not claim.exhausted
    assert redis.xautoclaim.await_args.args[3] == SCAN_LEASE_MS
    assert redis.xreadgroup.await_count == (0 if reclaimed else 1)


@pytest.mark.asyncio
async def test_replaced_pending_owner_does_not_receive_claim():
    redis = SimpleNamespace(
        eval=AsyncMock(return_value=1),
        xinfo_consumers=AsyncMock(return_value=[]),
        xautoclaim=AsyncMock(return_value=[b"0-0", [(b"1-0", {b"file_key": b"private"})]]),
        xpending_range=AsyncMock(return_value=[{"consumer": "another", "times_delivered": 2}]),
    )
    assert await DurableScanQueue(redis).claim() is None


@pytest.mark.asyncio
async def test_foreign_consumer_cannot_publish_or_renew():
    redis = SimpleNamespace(eval=AsyncMock())
    queue = DurableScanQueue(redis)
    claim = ScanClaim("1-0", "private", "another", 1)
    assert not await queue.publish(claim, "private-target", "private-body")
    assert not await queue.renew(claim)
    redis.eval.assert_not_awaited()


def test_claim_is_immutable_and_exhaustion_is_after_three_actual_deliveries():
    assert not ScanClaim("1-0", "private", "owner", 3).exhausted
    claim = ScanClaim("1-0", "private", "owner", 4)
    assert claim.exhausted
    with pytest.raises(FrozenInstanceError):
        claim.attempt = 1


@pytest.mark.parametrize(
    "fields",
    [
        {"file_key_hex": "ff"},
        {"file_key_hex": "invalid"},
        {"file_key_hex": "00"},
        {"invalid_source": "1"},
        {"file_key": "x" * 4097},
    ],
)
def test_invalid_migration_payload_receives_terminal_claim_without_raw_key(fields):
    assert _source_key(fields) is None


def test_hex_migration_preserves_unicode_storage_key():
    value = "fixture/материалы.txt"
    assert _source_key({"file_key_hex": value.encode().hex()}) == value


@pytest.mark.asyncio
async def test_consumer_retirement_skips_pending_and_rechecks_empty_candidates():
    redis = SimpleNamespace(
        eval=AsyncMock(),
        xinfo_consumers=AsyncMock(
            return_value=[
                {"name": "busy", "pending": 1, "idle": SCAN_LEASE_MS + 1},
                {"name": "active", "pending": 0, "idle": 1},
                {"name": "retired", "pending": 0, "idle": SCAN_LEASE_MS + 1},
            ]
        ),
    )
    queue = DurableScanQueue(redis)
    await queue.retire_idle_consumers()
    assert redis.eval.await_args.args[1:] == (1, queue.stream, queue.group, "retired")
    assert "'XPENDING'" in redis.eval.await_args.args[0]
    redis.eval.assert_awaited_once()
