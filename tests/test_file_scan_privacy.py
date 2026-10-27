"""Scan failures never publish raw storage exceptions or log object locators."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.files.application.scanning import service as file_scanner_service
from service.services.files.infrastructure.scan_queue import ScanClaim
from service.utils import file_scan_worker


class AsyncRedis(SimpleNamespace):
    async def execute_command(self, *_args, **_kwargs):
        return None


@pytest.fixture
def capture(monkeypatch, caplog):
    for logger in (file_scanner_service.logger, file_scan_worker.logger):
        monkeypatch.setattr(logger, "handlers", [caplog.handler])
        monkeypatch.setattr(logger, "propagate", False)
        caplog.set_level(logging.DEBUG, logger=logger.name)
    return caplog


@pytest.mark.asyncio
async def test_scanner_failure_returns_only_bounded_reason(capture):
    scanner = file_scanner_service.BasicFileScanner(
        SimpleNamespace(get_file=AsyncMock(side_effect=OSError("PRIVATE_STORAGE_BODY")))
    )
    result = await scanner.scan("PRIVATE_OBJECT_LOCATOR")
    assert result == {"status": "error", "reason": "unavailable"}
    assert "PRIVATE_STORAGE_BODY" not in capture.text
    assert "PRIVATE_OBJECT_LOCATOR" not in capture.text
    assert all(record.exc_info is None for record in capture.records)


@pytest.mark.asyncio
async def test_worker_projects_success_to_closed_metadata_before_publication(capture):
    queue = SimpleNamespace(
        claim=AsyncMock(return_value=ScanClaim("1-0", "fixture", "worker", 1)),
        publish=AsyncMock(return_value=True),
        renew=AsyncMock(return_value=True),
    )
    scanner = SimpleNamespace(
        scan=AsyncMock(
            return_value={
                "status": "ok",
                "size": 0,
                "sha256": "a" * 64,
                "provider_body": "PRIVATE_SCAN_PAYLOAD",
                "url": "PRIVATE_SCAN_URL",
            }
        )
    )
    assert await file_scan_worker.process_scan_once(object(), scanner, queue=queue) == 1
    result = json.loads(queue.publish.await_args.args[2])["result"]
    assert result == {"status": "ok", "size": 0, "sha256": "a" * 64}
    assert "PRIVATE_SCAN" not in capture.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        {"status": "PRIVATE_SCAN_STATUS"},
        {"status": "ok", "size": True, "sha256": "a" * 64},
        {"status": "ok", "size": -1, "sha256": "a" * 64},
        {"status": "ok", "size": 1.5, "sha256": "a" * 64},
        {"status": "ok", "size": "1", "sha256": "a" * 64},
        {"status": "ok", "size": 2**53, "sha256": "a" * 64},
        {"status": "ok", "size": 1, "sha256": "PRIVATE_SCAN_HASH"},
        {"status": "ok", "size": 1, "sha256": None},
        {"status": "ok"},
        {"status": "skipped", "reason": "PRIVATE_SCAN_REASON"},
        {"status": []},
    ],
)
async def test_unvalidated_scanner_result_stays_pending_without_publication(capture, result):
    queue = SimpleNamespace(
        claim=AsyncMock(return_value=ScanClaim("1-0", "fixture", "worker", 1)),
        publish=AsyncMock(return_value=True),
        renew=AsyncMock(return_value=True),
    )
    scanner = SimpleNamespace(scan=AsyncMock(return_value=result))
    assert await file_scan_worker.process_scan_once(object(), scanner, queue=queue) == 0
    queue.publish.assert_not_awaited()
    assert "PRIVATE_SCAN" not in capture.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_worker_logs_do_not_disclose_keys_results_or_exception(capture, failure):
    redis = AsyncRedis(
        lpop=AsyncMock(return_value="PRIVATE_OBJECT_LOCATOR"),
        xadd=AsyncMock(),
    )
    scanner = SimpleNamespace(
        scan=AsyncMock(
            return_value={"status": "ok", "size": 7, "sha256": "a" * 64},
            side_effect=OSError("PRIVATE_SCANNER_BODY") if failure else None,
        )
    )
    queue = SimpleNamespace(
        claim=AsyncMock(return_value=ScanClaim("1-0", "PRIVATE_OBJECT_LOCATOR", "worker", 1)),
        publish=AsyncMock(return_value=True),
        renew=AsyncMock(return_value=True),
    )
    result = await file_scan_worker.process_scan_once(redis, scanner, queue=queue)
    assert result == (0 if failure else 1)
    if failure:
        queue.publish.assert_not_awaited()
    else:
        queue.publish.assert_awaited_once()
    assert "PRIVATE_OBJECT_LOCATOR" not in capture.text
    assert "PRIVATE_SCANNER_BODY" not in capture.text
    assert "a" * 64 not in capture.text
    assert all(record.exc_info is None for record in capture.records)
