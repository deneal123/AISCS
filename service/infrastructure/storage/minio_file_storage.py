import asyncio
import logging
import os
from io import BytesIO
from typing import BinaryIO

import certifi
import urllib3

from service.settings import MinioConfig

from .abstract_file_storage import AbstractFileStorage

logger = logging.getLogger(__name__)


def _error_code(exc: Exception) -> str:
    """Return a bounded diagnostic without object keys, URLs, or response bodies."""
    return type(exc).__name__[:64]


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
            raise RuntimeError(f"Failed to create/verify MinIO bucket {self._bucket}") from e

    def build_file_path(self, folder: str, mode: str, file_name: str) -> str:
        """Build S3 object key from folder, mode, and filename"""
        return f"{folder}/{mode}/{file_name}"

    async def upload_file(self, *, file_key: str, file_data: bytes) -> str:
        """Upload file to MinIO with retry logic"""
        last_exc: Exception | None = None
        for i in range(max(1, self._retry_attempts)):
            try:
                length = len(file_data)
                # Блокирующий сетевой вызов MinIO выносим из event loop
                await asyncio.to_thread(
                    self._client.put_object,
                    bucket_name=self._bucket,
                    object_name=file_key,
                    data=BytesIO(file_data),
                    length=length,
                )
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

        last_exc: Exception | None = None
        for attempt in range(max(1, self._retry_attempts)):
            try:
                stream.seek(0)
                await asyncio.to_thread(
                    self._client.put_object,
                    bucket_name=self._bucket,
                    object_name=file_key,
                    data=stream,
                    length=length,
                )
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

    async def delete_file(self, *, file_key: str) -> None:
        """Delete file from MinIO with retry logic"""
        for i in range(max(1, self._retry_attempts)):
            try:
                await asyncio.to_thread(self._client.remove_object, self._bucket, file_key)
                logger.info("MinIO object deleted")
                return
            except Exception as e:
                logger.warning(
                    "MinIO delete failed: attempt=%s total=%s category=%s",
                    i + 1,
                    self._retry_attempts,
                    _error_code(e),
                )
                if i < self._retry_attempts - 1:
                    await asyncio.sleep(self._retry_backoff * (2**i))
                else:
                    # Non-fatal for cleanup flows
                    logger.error("MinIO delete exhausted retries; cleanup remains best-effort")
                    return

    async def get_presigned_url(self, *, file_key: str, expiry_sec: int | None = None) -> str:
        """Generate presigned URL for direct file download.

        The URL is rewritten to use public_endpoint so it's accessible from browser.
        """
        from datetime import timedelta
        from urllib.parse import urlparse

        expiry = expiry_sec if expiry_sec is not None else self._presign_expiry

        try:
            url = self._client.presigned_get_object(
                bucket_name=self._bucket,
                object_name=file_key,
                expires=timedelta(seconds=max(1, int(expiry))),
            )
            logger.debug("MinIO download capability created: expiry_sec=%s", int(expiry))

            # Replace internal endpoint with public endpoint for browser access
            if self._public_endpoint:
                # Build possible internal base URLs to replace
                internal_bases = [
                    f"http://{self.config.endpoint}",
                    f"https://{self.config.endpoint}",
                ]

                for internal_base in internal_bases:
                    if url.startswith(internal_base):
                        url = url.replace(internal_base, self._public_endpoint.rstrip("/"), 1)
                        break

                # Ensure the URL is absolute (has protocol)
                parsed = urlparse(url)
                if not parsed.scheme:
                    # URL doesn't have protocol, prepend public_endpoint
                    url = f"{self._public_endpoint.rstrip('/')}/{url.lstrip('/')}"

            return url
        except Exception as e:
            logger.error("MinIO download capability failed: category=%s", _error_code(e))
            # Fallback to s3:// style reference if presign fails
            return f"s3://{self._bucket}/{file_key}"

    async def get_presigned_upload_url(
        self, *, file_key: str, expiry_sec: int | None = None
    ) -> str:
        """Generate presigned URL for direct file upload (future use)"""
        from datetime import timedelta

        expiry = expiry_sec if expiry_sec is not None else self._presign_expiry

        try:
            url = self._client.presigned_put_object(
                bucket_name=self._bucket,
                object_name=file_key,
                expires=timedelta(seconds=max(1, int(expiry))),
            )
            logger.debug("MinIO upload capability created: expiry_sec=%s", int(expiry))
            return url
        except Exception as e:
            logger.error("MinIO upload capability failed: category=%s", _error_code(e))
            raise

    def file_exists(self, file_key: str) -> bool:
        """Check if file exists in MinIO"""
        try:
            self._client.stat_object(self._bucket, file_key)
            return True
        except Exception:
            return False

    async def get_file(self, file_key: str) -> bytes:
        """Download file from MinIO"""

        def _download() -> bytes:
            response = self._client.get_object(self._bucket, file_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        try:
            # Блокирующий сетевой вызов MinIO выносим из event loop
            data = await asyncio.to_thread(_download)
            logger.debug("MinIO download completed: size_bytes=%s", len(data))
            return data
        except Exception as e:
            logger.error("MinIO download failed: category=%s", _error_code(e))
            raise

    async def get_file_head(self, file_key: str, max_bytes: int) -> bytes:
        """Первые ``max_bytes`` байт — диапазонным запросом, а не целым файлом.

        Нужно классификации формы вложения: вердикт «таблица или словарь» выносится по
        голове, и качать ради него мегабайты — дороже самой задачи.
        """

        def _download_head() -> bytes:
            response = self._client.get_object(self._bucket, file_key, offset=0, length=max_bytes)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(_download_head)
