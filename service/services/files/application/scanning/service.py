import asyncio
import hashlib
import logging

from service.services.files.application.ports.interfaces import FileStoragePort
from service.services.files.application.scanning.metrics import file_scan_metrics
from service.services.files.domain.file_scan_result import safe_scan_result

logger = logging.getLogger(__name__)


class FileScanner:
    """Contract for file scanners."""

    async def scan(self, file_key: str) -> dict:
        raise NotImplementedError


class BasicFileScanner(FileScanner):
    """Simple scanner that reads file content and computes basic metadata (size, sha256).

    This is intentionally lightweight: in production it should call an antivirus engine or
    content analysis pipeline and produce structured results.
    """

    def __init__(self, storage: FileStoragePort):
        self.storage = storage

    async def scan(self, file_key: str) -> dict:
        try:
            metadata_reader = getattr(self.storage, "read_file_metadata", None)
            if callable(metadata_reader):
                result = safe_scan_result(await metadata_reader(file_key))
                if result is None or result["status"] != "ok":
                    raise ValueError("scan_metadata_invalid")
                file_scan_metrics.record("succeeded")
                return result
            # Try storage.get_file if available
            getter = getattr(self.storage, "get_file", None)
            if callable(getter):
                data = await getter(file_key)
            else:
                # If storage doesn't support download, try presigned URL as a fallback (not ideal)
                logger.warning(
                    "Storage download unavailable for scanning",
                    extra={"component": "file_scan", "failure_code": "no_download"},
                )
                file_scan_metrics.record("skipped")
                return {"status": "skipped", "reason": "no_download"}

            if not isinstance(data, (bytes, bytearray)):
                raise TypeError("invalid_scan_content")
            size = len(data)
            sha256 = hashlib.sha256(data).hexdigest()

            result = {"status": "ok", "size": size, "sha256": sha256}
            file_scan_metrics.record("succeeded")
            return result
        except asyncio.CancelledError:
            file_scan_metrics.record("cancelled")
            raise
        except Exception:
            file_scan_metrics.record("failed")
            logger.warning(
                "File scan unavailable",
                extra={"component": "file_scan", "failure_code": "unavailable"},
            )
            return {"status": "error", "reason": "unavailable"}
