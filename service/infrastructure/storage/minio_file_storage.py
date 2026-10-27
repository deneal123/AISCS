import asyncio
import logging
import os
from contextlib import contextmanager
from io import BytesIO
from itertools import islice
from typing import BinaryIO

import certifi
import urllib3

from service.services.files.domain.download_filename import attachment_disposition
from service.services.files.domain.file_media_type import attachment_media_type
from service.services.files.domain.file_read_limits import validate_head_limit
from service.services.files.domain.pending_upload import PendingUploadObject, PendingUploadPage
from service.settings import MinioConfig

from .abstract_file_storage import AbstractFileStorage
from .bounded_download import copy_bounded, download_limit, settled_thread
from .identity import storage_identity
from .scan_metadata_reader import read_scan_metadata
from .stream_upload_contract import validate_upload_length

logger = logging.getLogger(__name__)


def _error_code(exc: Exception) -> str:
    """Return a bounded diagnostic without object keys, URLs, or response bodies."""
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, (OSError, urllib3.exceptions.HTTPError)):
        return "transport"
    if isinstance(exc, ValueError):
        return "invalid"
    from minio.error import S3Error

    if isinstance(exc, S3Error):
        code = exc.code
        if code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
            return "auth"
        if code in {"NoSuchBucket", "NoSuchKey"}:
            return "missing"
        if code == "SlowDown":
            return "rate_limit"
        if code == "RequestTimeout":
            return "timeout"
        return "remote"
    return "internal"


class MinioFileStorage(AbstractFileStorage):
    """S3/MinIO storage backend with presigned URLs support.

    Uses MinioConfig from settings for configuration.
    Supports:
    - File upload/download/delete
    - Presigned URLs for secure direct access
    - Automatic bucket creation
    - Retry logic with exponential backoff
    """

    def __init__(self, config: MinioConfig) -> None:
        try:
            from minio import Minio  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "Minio client not installed. Please `pip install minio` to use MinioFileStorage"
            ) from e

        self.config = config
        self._bucket = config.bucket
        self._namespace_id = storage_identity(
            "minio", config.endpoint, config.bucket, "tls" if config.secure else "plain"
        )
        self._retry_attempts = config.retry_attempts
        self._retry_backoff = config.retry_backoff
        self._presign_expiry = config.presign_expiry
        self._public_endpoint = config.public_endpoint

        # Initialize MinIO client
        self._client = Minio(
            endpoint=config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=config.secure,
            region=config.region,
            http_client=urllib3.PoolManager(
                timeout=urllib3.Timeout(connect=10, read=300),
                maxsize=10,
                cert_reqs="CERT_REQUIRED",
                ca_certs=os.environ.get("SSL_CERT_FILE") or certifi.where(),
                # Retry ownership belongs to this adapter. The SDK default logs
                # endpoint and bucket details for every connection retry.
                retries=urllib3.Retry(total=0, redirect=0),
            ),
        )

        # Ensure bucket exists (idempotent)
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self) -> None:
        """Create bucket if it doesn't exist"""
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket, location=self.config.region)
                logger.info("MinIO bucket created")
            else:
                logger.debug("MinIO bucket is ready")
        except Exception as e:
            logger.error("MinIO bucket check failed: category=%s", _error_code(e))
            raise RuntimeError("storage_init_failed") from None

    def build_file_path(self, folder: str, mode: str, file_name: str) -> str:
        """Build S3 object key from folder, mode, and filename"""
        return f"{folder}/{mode}/{file_name}"

    @property
    def namespace_id(self) -> str:
        # This describes the constructed SDK target, not a later mutable config.
        return self._namespace_id

    async def pending_upload_page(
        self, prefix: str, cursor: str | None, limit: int = 128
    ) -> PendingUploadPage:
        """Bounded inventory; cursor and keys remain private to maintenance."""
        if not prefix.endswith("/pending/") or (cursor and not cursor.startswith(prefix)):
            raise ValueError("pending_inventory_invalid")
        if not 1 <= limit <= 128:
            raise ValueError("pending_inventory_invalid")

        def read() -> PendingUploadPage:
            listing = self._client.list_objects(
                self._bucket, prefix=prefix, recursive=True, start_after=cursor
            )
            rows = list(islice(listing, limit + 1))
            objects = tuple(
                PendingUploadObject(row.object_name, row.last_modified, row.etag, row.size)
                for row in rows[:limit]
            )
            next_cursor = rows[limit - 1].object_name if len(rows) > limit else None
            return PendingUploadPage(objects, next_cursor)

        return await asyncio.to_thread(read)

    async def pending_upload_stat(self, key: str) -> PendingUploadObject | None:
        from minio.error import S3Error

        try:
            row = await asyncio.to_thread(self._client.stat_object, self._bucket, key)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return None
            raise RuntimeError("pending_inventory_unavailable") from None
        return PendingUploadObject(key, row.last_modified, row.etag, row.size)

    async def upload_file(self, *, file_key: str, file_data: bytes) -> str:
        """Upload file to MinIO with retry logic"""
        last_exc: Exception | None = None
        for i in range(max(1, self._retry_attempts)):
            try:
                length = len(file_data)
                # Блокирующий сетевой вызов MinIO выносим из event loop
                with BytesIO(file_data) as stream:
                    await self._upload_stream_once(file_key, stream, length)
                logger.info("MinIO upload completed: size_bytes=%s", length)
                return f"s3://{self._bucket}/{file_key}"
            except Exception as e:  # noqa: BLE001
                last_exc = e
                logger.warning(
                    "MinIO upload failed: attempt=%s total=%s category=%s",
                    i + 1,
                    self._retry_attempts,
                    _error_code(e),
                )
                if i < self._retry_attempts - 1:
                    await asyncio.sleep(self._retry_backoff * (2**i))
                else:
                    logger.error("MinIO upload exhausted retries: total=%s", self._retry_attempts)
                    raise

        # Should not reach here
        if last_exc:
            raise last_exc
        return f"s3://{self._bucket}/{file_key}"

    async def upload_file_stream(self, *, file_key: str, stream: BinaryIO, length: int) -> str:
        """Upload a bounded seekable stream without materialising it as bytes."""
        length = validate_upload_length(length)
        last_exc: Exception | None = None
        for attempt in range(max(1, self._retry_attempts)):
            try:
                stream.seek(0)
                await self._upload_stream_once(file_key, stream, length)
                logger.info("MinIO stream upload completed: size_bytes=%s", length)
                return f"s3://{self._bucket}/{file_key}"
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "MinIO stream upload failed: attempt=%s total=%s category=%s",
                    attempt + 1,
                    self._retry_attempts,
                    _error_code(exc),
                )
                if attempt < self._retry_attempts - 1:
                    await asyncio.sleep(self._retry_backoff * (2**attempt))
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("stream upload unavailable")

    async def _upload_stream_once(self, file_key: str, stream: BinaryIO, length: int) -> None:
        # Cancelling to_thread does not stop the SDK. Keep the caller's stream
        # alive until this attempt terminates under the configured HTTP timeout.
        # Cancellation must never enter the retry loop or leave a late commit
        # racing the caller's compensation.
        transfer = asyncio.create_task(
            asyncio.to_thread(
                self._client.put_object,
                bucket_name=self._bucket,
                object_name=file_key,
                data=stream,
                length=length,
                content_type=attachment_media_type(file_key),
            )
        )
        try:
            await asyncio.shield(transfer)
        except asyncio.CancelledError:
            while not transfer.done():
                try:
                    await asyncio.shield(transfer)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not transfer.cancelled():
                transfer.exception()  # Consume a late failure without exposing its body.
            raise

    async def delete_file(self, *, file_key: str) -> None:
        """Acknowledge deletion or confirmed absence; never swallow an outage."""
        from minio.error import S3Error

        for i in range(max(1, self._retry_attempts)):
            try:
                await asyncio.to_thread(self._client.remove_object, self._bucket, file_key)
                logger.info("MinIO object deleted")
                return
            except Exception as e:
                if isinstance(e, S3Error) and e.code == "NoSuchKey":
                    return
                logger.warning(
                    "MinIO delete failed: attempt=%s total=%s category=%s",
                    i + 1,
                    self._retry_attempts,
                    _error_code(e),
                )
                if i < self._retry_attempts - 1:
                    await asyncio.sleep(self._retry_backoff * (2**i))
                else:
                    raise RuntimeError("storage_delete_failed") from None

    def _browser_url(self, url: str) -> str:
        from urllib.parse import urlsplit

        if not self._public_endpoint:
            return url
        public = self._public_endpoint.rstrip("/")
        for scheme in ("http", "https"):
            internal = f"{scheme}://{self.config.endpoint}"
            if url.startswith(internal + "/"):
                return public + url[len(internal) :]
        if not urlsplit(url).scheme:
            return f"{public}/{url.lstrip('/')}"
        return url

    async def get_presigned_url(
        self, *, file_key: str, expiry_sec: int | None = None, download_name: str | None = None
    ) -> str:
        """Generate presigned URL for direct file download.

        The URL is rewritten to use public_endpoint so it's accessible from browser.
        """
        from datetime import timedelta

        expiry = expiry_sec if expiry_sec is not None else self._presign_expiry

        try:
            response_headers = {"response-cache-control": "private, no-store"}
            if download_name is not None:
                response_headers.update(
                    {
                        "response-content-disposition": attachment_disposition(download_name),
                        "response-content-type": attachment_media_type(download_name),
                    }
                )
            url = self._client.presigned_get_object(
                bucket_name=self._bucket,
                object_name=file_key,
                expires=timedelta(seconds=max(1, int(expiry))),
                response_headers=response_headers,
            )
            logger.debug("MinIO download capability created: expiry_sec=%s", int(expiry))

            return self._browser_url(url)
        except Exception as e:
            logger.error("MinIO download capability failed: category=%s", _error_code(e))
            # An internal locator is not a browser-download capability.
            raise RuntimeError("storage_presign_failed") from None

    async def get_presigned_upload_url(
        self, *, file_key: str, expiry_sec: int | None = None
    ) -> str:
        """Generate an upload capability using the configured browser-facing proxy."""
        from datetime import timedelta

        expiry = expiry_sec if expiry_sec is not None else self._presign_expiry

        try:
            url = self._client.presigned_put_object(
                bucket_name=self._bucket,
                object_name=file_key,
                expires=timedelta(seconds=max(1, int(expiry))),
            )
            logger.debug("MinIO upload capability created: expiry_sec=%s", int(expiry))
            return self._browser_url(url)
        except Exception as e:
            logger.error("MinIO upload capability failed: category=%s", _error_code(e))
            raise RuntimeError("storage_presign_failed") from None

    def file_exists(self, file_key: str) -> bool:
        """Check if file exists in MinIO"""
        try:
            self._client.stat_object(self._bucket, file_key)
            return True
        except Exception:
            return False

    async def commit_presigned_upload(
        self, *, source_key: str, destination_key: str, max_bytes: int
    ) -> None:
        """Freeze a bounded uploaded object without materializing its bytes."""
        from minio.commonconfig import CopySource

        def copy() -> None:
            stat = self._client.stat_object(self._bucket, source_key)
            if stat.size is None or stat.size < 0 or stat.size > max_bytes or not stat.etag:
                raise ValueError("invalid_upload_object")
            self._client.copy_object(
                self._bucket,
                destination_key,
                CopySource(self._bucket, source_key, match_etag=stat.etag),
            )
            published = self._client.stat_object(self._bucket, destination_key)
            if published.size != stat.size:
                raise ValueError("invalid_upload_object")

        task = asyncio.create_task(asyncio.to_thread(copy))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if task.done() and not task.cancelled():
                task.exception()
            raise
        except Exception:
            raise RuntimeError("storage_upload_commit_failed") from None

    async def read_file_metadata(self, file_key: str) -> dict:
        @contextmanager
        def open_stream():
            response = self._client.get_object(self._bucket, file_key)
            try:
                yield response
            finally:
                try:
                    response.close()
                finally:
                    response.release_conn()

        return await read_scan_metadata(open_stream)

    async def get_file(self, file_key: str) -> bytes:
        """Download file from MinIO"""

        def _download() -> bytes:
            response = self._client.get_object(self._bucket, file_key)
            try:
                return response.read()
            finally:
                try:
                    response.close()
                finally:
                    response.release_conn()

        try:
            # Блокирующий сетевой вызов MinIO выносим из event loop
            data = await asyncio.to_thread(_download)
            logger.debug("MinIO download completed: size_bytes=%s", len(data))
            return data
        except Exception as e:
            logger.error("MinIO download failed: category=%s", _error_code(e))
            raise

    async def download_file_stream(self, *, file_key: str, target: BinaryIO, max_bytes: int) -> int:
        limit = download_limit(max_bytes)

        def read() -> int:
            # Bound upstream transfer too. The sentinel detects overflow even
            # when the server ignores Range or reports a misleading length.
            # S3 rejects Range on an empty object. For a zero allowance use the
            # SDK's non-preloaded GET, read only the sentinel and close it.
            response = (
                self._client.get_object(self._bucket, file_key, offset=0, length=limit + 1)
                if limit
                else self._client.get_object(self._bucket, file_key)
            )
            try:
                return copy_bounded(response, target, limit)
            finally:
                try:
                    response.close()
                finally:
                    response.release_conn()

        return await settled_thread(read)

    async def get_file_head(self, file_key: str, max_bytes: int) -> bytes:
        """Первые ``max_bytes`` байт — диапазонным запросом, а не целым файлом.

        Нужно классификации формы вложения: вердикт «таблица или словарь» выносится по
        голове, и качать ради него мегабайты — дороже самой задачи.
        """
        max_bytes = validate_head_limit(max_bytes)

        def _download_head() -> bytes:
            response = self._client.get_object(self._bucket, file_key, offset=0, length=max_bytes)
            try:
                return response.read(max_bytes)
            finally:
                try:
                    response.close()
                finally:
                    response.release_conn()

        return await asyncio.to_thread(_download_head)
