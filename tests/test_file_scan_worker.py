import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.files.infrastructure.scan_queue import ScanClaim
from service.utils import file_scan_worker
from service.utils.file_scan_worker import process_scan_once


class FakeRedis:
    """⚠️ `execute_command` — по нему код узнаёт асинхронный клиент. Без него двойник
    выглядит СИНХРОННЫМ, вызов уходит в поток и молча не исполняется."""

    async def execute_command(self, *args, **kwargs):
        return None

    def __init__(self, to_pop=None):
        self.to_pop = to_pop or []
        self.published = []

    async def lpop(self, key):
        if self.to_pop:
            return self.to_pop.pop(0)
        return None

    async def xadd(self, key, mapping):
        self.published.append((key, mapping))


class FakeScanner:
    def __init__(self):
        self.scanned = []

    async def scan(self, file_key: str):
        self.scanned.append(file_key)
        return {"status": "ok", "size": 1, "sha256": "a" * 64}


@pytest.mark.asyncio
async def test_process_scan_once_publishes_result():
    fake_redis = FakeRedis(to_pop=[b"folder/file.jpg"])
    scanner = FakeScanner()

    queue = SimpleNamespace(
        claim=AsyncMock(return_value=ScanClaim("1-0", "folder/file.jpg", "worker", 1)),
        publish=AsyncMock(return_value=True),
        renew=AsyncMock(return_value=True),
    )
    res = await process_scan_once(fake_redis, scanner, queue=queue)
    assert res == 1
    assert scanner.scanned == ["folder/file.jpg"]
    queue.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_scan_once_no_item():
    fake_redis = FakeRedis(to_pop=[])
    scanner = FakeScanner()

    queue = SimpleNamespace(claim=AsyncMock(return_value=None))
    res = await process_scan_once(fake_redis, scanner, queue=queue)
    assert res == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("scanner", [None, SimpleNamespace(scan=None)])
async def test_missing_scanner_does_not_consume_queued_file(scanner):
    redis = FakeRedis(to_pop=[b"pending-file"])
    assert await process_scan_once(redis, scanner) == 0
    assert redis.to_pop == [b"pending-file"]
    assert not redis.published


@pytest.mark.asyncio
async def test_loop_exits_before_dequeue_when_scanner_is_not_registered(monkeypatch):
    redis = FakeRedis(to_pop=[b"pending-file"])
    current = SimpleNamespace(infra=SimpleNamespace(redis_client=redis, file_scanner=None))
    monkeypatch.setattr(file_scan_worker.container, "get_current_container", lambda: current)
    # Bound the old loop without waiting: sleep would follow the destructive pop.
    sleep = AsyncMock(side_effect=RuntimeError("test-loop-boundary"))
    monkeypatch.setattr(file_scan_worker.asyncio, "sleep", sleep)
    try:
        await file_scan_worker.scan_loop()
    except RuntimeError:
        pass
    assert redis.to_pop == [b"pending-file"]
    sleep.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [False, OSError("private-publish-marker")])
async def test_unconfirmed_publication_is_not_success_or_retried(outcome):
    queue = SimpleNamespace(
        claim=AsyncMock(return_value=ScanClaim("1-0", "fixture", "worker", 1)),
        publish=AsyncMock(
            return_value=outcome if outcome is False else None,
            side_effect=outcome if isinstance(outcome, OSError) else None,
        ),
        renew=AsyncMock(return_value=True),
    )
    scanner = SimpleNamespace(
        scan=AsyncMock(return_value={"status": "ok", "size": 1, "sha256": "a" * 64})
    )
    assert await process_scan_once(object(), scanner, queue=queue) == 0
    queue.publish.assert_awaited_once()
    scanner.scan.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt", [1, 3, 4])
async def test_scan_failure_remains_pending_until_bounded_terminal_attempt(attempt):
    queue = SimpleNamespace(
        claim=AsyncMock(return_value=ScanClaim("1-0", "fixture", "worker", attempt)),
        publish=AsyncMock(return_value=True),
        renew=AsyncMock(return_value=True),
    )
    scanner = SimpleNamespace(
        scan=AsyncMock(return_value={"status": "error", "reason": "unavailable"})
    )
    result = await process_scan_once(object(), scanner, queue=queue)
    assert result == (1 if attempt == 4 else 0)
    assert scanner.scan.await_count == (0 if attempt == 4 else 1)
    assert queue.publish.await_count == (1 if attempt == 4 else 0)


@pytest.mark.asyncio
async def test_invalid_claim_has_bounded_terminal_disposition_without_scanning():
    queue = SimpleNamespace(
        claim=AsyncMock(return_value=ScanClaim("1-0", None, "worker", 1)),
        publish=AsyncMock(return_value=True),
        failures="private-failures",
    )
    scanner = SimpleNamespace(scan=AsyncMock())
    assert await process_scan_once(object(), scanner, queue=queue) == 1
    scanner.scan.assert_not_awaited()
    assert queue.publish.await_args.args[1:] == (
        "private-failures",
        '{"event": "scan_failed", "reason": "invalid"}',
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "deadline", "lease"])
async def test_interrupted_scan_closes_tasks_and_never_publishes(failure, monkeypatch):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def scan(_key):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    queue = SimpleNamespace(
        claim=AsyncMock(return_value=ScanClaim("1-0", "fixture", "worker", 1)),
        publish=AsyncMock(),
        renew=AsyncMock(return_value=failure != "lease"),
    )
    if failure == "deadline":
        monkeypatch.setattr(file_scan_worker, "SCAN_TIMEOUT_SEC", 0.01)
    if failure == "lease":
        monkeypatch.setattr(file_scan_worker, "SCAN_HEARTBEAT_SEC", 0.001)
    task = asyncio.create_task(process_scan_once(object(), SimpleNamespace(scan=scan), queue=queue))
    await asyncio.wait_for(started.wait(), 1)
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
    else:
        assert await asyncio.wait_for(task, 1) == 0
    assert stopped.is_set()
    queue.publish.assert_not_awaited()
