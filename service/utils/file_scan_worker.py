import asyncio
import json
import logging
from typing import Any

from service.composition import state as container
from service.services.files.domain.file_scan_result import safe_scan_result
from service.services.files.infrastructure.scan_queue import DurableScanQueue, ScanClaim

logger = logging.getLogger(__name__)

SCAN_QUEUE_KEY = "file:scan:queue"
SCAN_TIMEOUT_SEC = 300
SCAN_HEARTBEAT_SEC = 30


async def _scan_with_lease(scan, claim: ScanClaim, queue: DurableScanQueue):
    async def heartbeat():
        while True:
            await asyncio.sleep(SCAN_HEARTBEAT_SEC)
            if not await queue.renew(claim):
                return

    scanning = asyncio.create_task(scan(claim.file_key))
    renewing = asyncio.create_task(heartbeat())
    try:
        async with asyncio.timeout(SCAN_TIMEOUT_SEC):
            done, _ = await asyncio.wait((scanning, renewing), return_when=asyncio.FIRST_COMPLETED)
            if renewing in done:
                renewing.result()
                return None
            return scanning.result()
    finally:
        for task in (scanning, renewing):
            if not task.done():
                task.cancel()
        await asyncio.gather(scanning, renewing, return_exceptions=True)


async def process_scan_once(
    redis_client: Any, scanner: Any, *, queue: DurableScanQueue | None = None
) -> int:
    """Return 1 only after a fenced result commit; failed/uncertain work stays pending."""
    try:
        scan = getattr(scanner, "scan", None)
        if not callable(scan):
            logger.warning(
                "File scanner unavailable",
                extra={"component": "file_scan", "failure_code": "unavailable"},
            )
            return 0

        if redis_client is None:
            return 0
        queue = queue or DurableScanQueue(redis_client)
        claim = await queue.claim()
        if claim is None:
            return 0
        if claim.file_key is None:
            payload = json.dumps({"event": "scan_failed", "reason": "invalid"})
            return int(await queue.publish(claim, queue.failures, payload))
        logger.info("Processing file scan", extra={"component": "file_scan"})
        result = (
            {"status": "error", "reason": "unavailable"}
            if claim.exhausted
            else await _scan_with_lease(scan, claim, queue)
        )
        result = safe_scan_result(result)
        if result is None or (result["status"] == "error" and not claim.exhausted):
            return 0
        payload_json = json.dumps(
            {"event": "scanned", "file_key": claim.file_key, "result": result}
        )
        if not await queue.publish(claim, f"file:{claim.file_key}:stream", payload_json):
            return 0
        logger.info("File scan processed", extra={"component": "file_scan"})
        return 1

    except asyncio.CancelledError:
        raise
    except Exception:
        if isinstance(queue, DurableScanQueue):
            queue.invalidate()
        logger.warning(
            "File scan processing unavailable",
            extra={"component": "file_scan", "failure_code": "unavailable"},
        )
        return 0


async def scan_loop():
    """Main loop to run as a background task, popping items and scanning them."""
    try:
        redis_client = None
        try:
            redis_client = container.get_current_container().infra.redis_client
        except Exception:
            redis_client = None

        scanner = None
        try:
            scanner = container.get_current_container().infra.file_scanner
            if not callable(getattr(scanner, "scan", None)):
                logger.warning(
                    "File scanner unavailable",
                    extra={"component": "file_scan", "failure_code": "unavailable"},
                )
                return
        except Exception:
            logger.warning("FileScanner not registered; exiting scan loop")
            return

        if redis_client is None:
            return
        queue = DurableScanQueue(redis_client)
        try:
            while True:
                processed = await process_scan_once(redis_client, scanner, queue=queue)
                if processed == 0:
                    await asyncio.sleep(1)
        finally:
            try:
                async with asyncio.timeout(5):
                    await queue.close()
            except Exception:
                logger.debug(
                    "Scan consumer cleanup unavailable",
                    extra={"component": "file_scan", "failure_code": "unavailable"},
                )
    except asyncio.CancelledError:
        logger.info("File scan loop cancelled")
        raise
    except Exception:
        logger.warning(
            "File scan loop unavailable",
            extra={"component": "file_scan", "failure_code": "unavailable"},
        )
        # bubble up to background manager which will restart the task
        raise RuntimeError("file_scan_unavailable") from None
