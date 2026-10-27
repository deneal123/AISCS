import asyncio
import base64
import hashlib
import logging
import re
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, status

from service.models.db.db_models import UserFile
from service.models.file_models import FileMetadataLogic
from service.models.key_value import ServiceType
from service.services.files.application.commit_resolution import settle_cancelled_metadata
from service.services.files.application.dto import (
    FetchUserFilesResponse,
    FileMetadata,
    UploadResponse,
)
from service.services.files.application.library_file_type import library_file_type
from service.services.files.application.ports.interfaces import FileStoragePort, MessageBusPort
from service.services.files.domain.file_read_limits import normalize_file_head, validate_head_limit
from service.services.files.persistence.file_repository import FileRepository
from service.shared.repositories.exceptions import RepositoryIntegrityError

logger = logging.getLogger(__name__)


class InvalidLibraryCursor(ValueError):
    pass


class UploadIntentConflict(ValueError):
    pass


def _workspace_filename(value: object) -> str:
    """Derive the only workspace-visible name from an uploader-facing label."""
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()


def _legacy_library_filename(row: UserFile) -> str:
    """Name a pre-v2 library row without exposing its storage key.

    Historical rows predate ``original_name``.  They remain valid account
    files, so hiding them made Library look empty even though a user had a
    perfectly usable source.  The opaque file id is safe to show; only retain
    a conservative extension from the storage key for a useful file picker.
    """
    original = _workspace_filename(getattr(row, "original_name", ""))
    if original:
        return original[:1_000]
    suffix = Path(str(getattr(row, "file_name", "") or "")).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,12}", suffix):
        suffix = ""
    return f"Ранее загруженный файл {str(row.id)[:8]}{suffix}"


class FileSaverService:
    def __init__(
        self,
        repository: FileRepository,
        folder_name: str,
        file_storage: FileStoragePort,
        message_bus: MessageBusPort | None = None,
        upload_cache=None,
    ) -> None:
        if file_storage is None:
            raise ValueError("file_storage is required for FileSaverService")
        self.storage = file_storage
        self.message_bus = message_bus
        self.upload_cache = upload_cache
        self.repository = repository
        self.folder = folder_name

    async def fetch_all_user_files(
        self, user_id: uuid.UUID, mode: ServiceType
    ) -> FetchUserFilesResponse:
        logger.debug("fetching user files", extra={"component": "file_library"})

        user_files = await self.repository.fetch_user_files_metadata(user_id, mode)

        logger.debug(
            "user files fetched",
            extra={"component": "file_library", "result_count": len(user_files)},
        )

        if not user_files:
            return FetchUserFilesResponse(files=[])

        response = FetchUserFilesResponse(
            files=[FileMetadata(file_id=file.id, file_url=file.file_url) for file in user_files]
        )
        return response

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID] | None:
        value = str(cursor or "").strip()
        if not value:
            return None
        try:
            padding = "=" * (-len(value) % 4)
            decoded = base64.urlsafe_b64decode(value + padding).decode("ascii")
            timestamp, file_id = decoded.split("|", 1)
            return datetime.fromisoformat(timestamp), uuid.UUID(file_id)
        except (UnicodeDecodeError, ValueError) as exc:
            raise InvalidLibraryCursor("invalid library cursor") from exc

    @staticmethod
    def _encode_cursor(row: UserFile) -> str | None:
        if row.created_at is None:
            return None
        value = f"{row.created_at.isoformat()}|{row.id}".encode("ascii")
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    async def list_chat_library_page(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 200,
        offset: int = 0,
        cursor: str = "",
        search: str = "",
    ) -> dict:
        """Return safe metadata for persistent chat files.

        Workspace consumers must never infer a library from historic chat
        metadata: attachment rows contain no stable file identity and can
        outlive the underlying object.  The file repository is authoritative.
        """
        page_size = max(1, min(int(limit), 500))
        before = self._decode_cursor(cursor)
        page_options = {"limit": page_size + 1, "offset": max(0, int(offset))}
        if search.strip():
            page_options["search"] = search.strip()[:200]
        if before is not None:
            page_options["before"] = before
        rows = await self.repository.fetch_user_files_metadata(
            user_id, ServiceType.CHAT, **page_options
        )
        items: list[dict] = []
        for row in rows[:page_size]:
            name = _legacy_library_filename(row)
            items.append(
                {
                    "file_id": str(row.id),
                    "name": name,
                    "file_type": library_file_type(name),
                    "availability": "ready",
                }
            )
        return {
            "items": items,
            "next_cursor": (
                self._encode_cursor(rows[page_size - 1]) if len(rows) > page_size else None
            ),
            "next_offset": (max(0, int(offset)) + page_size) if len(rows) > page_size else None,
        }

    async def list_chat_library(self, user_id: uuid.UUID, *, limit: int = 200) -> list[dict]:
        """Compatibility view used by older non-paginated consumers."""
        return (await self.list_chat_library_page(user_id, limit=limit))["items"]

    async def resolve_chat_library_import(
        self, user_id: uuid.UUID, file_id: uuid.UUID, *, expiry_sec: int
    ) -> dict:
        """Resolve one owned library file for an internal workspace import.

        The returned URL is only for backend-to-sidecar transport.  Callers
        must not put it into an HTTP response, stream event, metric, or log.
        """
        row = await self.repository.fetch_user_file_by_id(user_id, file_id)
        if row is None or getattr(row, "type", None) != ServiceType.CHAT:
            raise ValueError("library file not found")
        name = _legacy_library_filename(row)
        url = await self.get_presigned_url_by_key(
            file_key=str(row.file_name), expiry_sec=max(1, min(int(expiry_sec), 300))
        )
        if not url:
            raise ValueError("library file is unavailable")
        digest = str(getattr(row, "content_sha256", "") or "").lower()
        return {
            "name": name[:1_000],
            "url": url,
            **({"sha256": digest} if re.fullmatch(r"[0-9a-f]{64}", digest) else {}),
        }

    async def read_chat_library_bytes(self, user_id: uuid.UUID, file_id: uuid.UUID) -> bytes:
        from service.services.files.application.library_read import read_library_bytes

        return await read_library_bytes(self.repository, self.storage, user_id, file_id)

    async def save(
        self,
        user_id: uuid.UUID,
        mode: ServiceType,
        file_name: str,
        file_content: bytes,
        upload_intent_id: uuid.UUID | None = None,
    ) -> UploadResponse:
        digest = hashlib.sha256(file_content).hexdigest()
        safe_name = str(file_name or "").strip() or None
        if upload_intent_id is not None:
            existing = await self.repository.fetch_user_file_by_upload_intent(
                user_id, upload_intent_id
            )
            if existing is not None:
                return self._reused_upload(existing, safe_name, digest)

        masked_file_name = self._generate_file_name(file_name)

        file_key = self.storage.build_file_path(self.folder, mode.value, masked_file_name)

        try:
            file_url = await self.storage.upload_file(
                file_key=file_key,
                file_data=file_content,
            )
        except asyncio.CancelledError:
            await self._cleanup_cancelled_upload(file_key)
            raise
        except Exception:
            await self._delete_uploaded_object(file_key)
            raise

        file_metadata = UserFile(
            user_id=user_id,
            type=mode,
            file_name=file_key,
            # Имя, под которым файл прислал человек. Ключ хранилища обезличен намеренно
            # (столкновения имён, безопасность пути), но показывать в рабочем каталоге
            # надо именно это — см. `UserFile.original_name`.
            original_name=safe_name,
            upload_intent_id=upload_intent_id,
            content_sha256=digest,
            file_url=file_url,
        )

        try:
            saved_metadata = await self.repository.add_file_metadata(file_metadata)
        except asyncio.CancelledError:
            await settle_cancelled_metadata(
                self._recover_metadata_commit(user_id, file_key, safe_name, digest)
            )
            raise
        except RepositoryIntegrityError:
            await self._delete_uploaded_object(file_key)
            if upload_intent_id is None:
                raise
            existing = await self.repository.fetch_user_file_by_upload_intent(
                user_id, upload_intent_id
            )
            if existing is None:
                raise
            return self._reused_upload(existing, safe_name, digest)
        except Exception:
            recovered = await self._recover_metadata_commit(user_id, file_key, safe_name, digest)
            if recovered is not None:
                return recovered
            raise
        logger.debug("file metadata saved", extra={"component": "file_library"})
        return UploadResponse(file_id=saved_metadata.id, file_url=file_url, file_key=file_key)

    async def save_stream(
        self,
        user_id: uuid.UUID,
        mode: ServiceType,
        file_name: str,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int,
        expected_sha256: str,
        upload_intent_id: uuid.UUID,
        max_bytes: int = 256 * 1024 * 1024,
        before_persist: Callable[[], Awaitable[None]] | None = None,
    ) -> UploadResponse:
        """Persist a generated artifact with bounded disk spooling and integrity checks."""

        safe_name = str(file_name or "").strip() or None
        expected_sha256 = str(expected_sha256 or "").lower()
        if (
            type(expected_size) is not int
            or expected_size < 1
            or expected_size > max_bytes
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        ):
            raise ValueError("artifact_integrity")
        existing = await self.repository.fetch_user_file_by_upload_intent(user_id, upload_intent_id)
        if existing is not None:
            return self._reused_upload(existing, safe_name, expected_sha256)

        digest = hashlib.sha256()
        size = 0
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as spool:
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise ValueError("artifact_integrity")
                if not chunk:
                    continue
                size += len(chunk)
                if size > expected_size or size > max_bytes:
                    raise ValueError("artifact_too_large")
                digest.update(chunk)
                spool.write(chunk)
            if size != expected_size or digest.hexdigest() != expected_sha256:
                raise ValueError("artifact_integrity")
            spool.seek(0)

            masked_file_name = self._generate_file_name(file_name)
            file_key = self.storage.build_file_path(self.folder, mode.value, masked_file_name)
            uploader = getattr(self.storage, "upload_file_stream", None)
            if not callable(uploader):
                raise RuntimeError("stream_storage_unavailable")
            if before_persist is not None:
                await before_persist()
            try:
                file_url = await uploader(file_key=file_key, stream=spool, length=size)
            except asyncio.CancelledError:
                # The storage adapter drains its blocking transfer before
                # returning cancellation. This key is unique to this attempt;
                # no metadata has been attempted and no other retry owns it.
                await self._cleanup_cancelled_upload(file_key)
                raise
            except Exception:
                # A lost upload acknowledgement is not proof that the object
                # was never committed. Only this UUID-key belongs to the failed
                # attempt, and metadata has not been attempted yet.
                await self._delete_uploaded_object(file_key)
                raise

        if before_persist is not None:
            try:
                await before_persist()
            except asyncio.CancelledError:
                # Metadata has not been attempted. Repeated disconnects must
                # not interrupt compensation of this attempt's unique object.
                await self._cleanup_cancelled_upload(file_key)
                raise
            except BaseException:
                # The upload has completed, but metadata has not been attempted:
                # ownership/cancellation failure can safely compensate this object.
                await self._delete_uploaded_object(file_key)
                raise

        file_metadata = UserFile(
            user_id=user_id,
            type=mode,
            file_name=file_key,
            original_name=safe_name,
            upload_intent_id=upload_intent_id,
            content_sha256=expected_sha256,
            file_url=file_url,
        )
        try:
            saved_metadata = await self.repository.add_file_metadata(file_metadata)
        except asyncio.CancelledError:
            await settle_cancelled_metadata(
                self._recover_metadata_commit(user_id, file_key, safe_name, expected_sha256)
            )
            raise
        except RepositoryIntegrityError:
            await self._delete_uploaded_object(file_key)
            existing = await self.repository.fetch_user_file_by_upload_intent(
                user_id, upload_intent_id
            )
            if existing is None:
                raise
            return self._reused_upload(existing, safe_name, expected_sha256)
        except Exception:
            recovered = await self._recover_metadata_commit(
                user_id, file_key, safe_name, expected_sha256
            )
            if recovered is not None:
                return recovered
            raise
        return UploadResponse(file_id=saved_metadata.id, file_url=file_url, file_key=file_key)

    async def _recover_metadata_commit(
        self, user_id: uuid.UUID, file_key: str, safe_name: str | None, digest: str
    ) -> UploadResponse | None:
        """Resolve a lost commit acknowledgement before compensating its object.

        The repository read opens a fresh transaction and is bound to the owner
        and exact generated key, including uploads without an intent. A failed
        read is not proof of rollback: retain the object rather than destroying
        a potentially committed Library file.
        """
        try:
            async with asyncio.timeout(30):
                row = await self.repository.fetch_user_file_by_name(user_id, file_key)
        except Exception:
            logger.warning(
                "file metadata commit unresolved",
                extra={"component": "file_library", "failure_code": "unavailable"},
            )
            raise RuntimeError("metadata_unconfirmed") from None
        if row is not None:
            return self._reused_upload(row, safe_name, digest)
        await self._delete_uploaded_object(file_key)
        return None

    @staticmethod
    def _reused_upload(row: UserFile, safe_name: str | None, digest: str) -> UploadResponse:
        if row.content_sha256 != digest or row.original_name != safe_name:
            raise UploadIntentConflict("upload_intent_conflict")
        return UploadResponse(
            file_id=row.id,
            file_url=row.file_url,
            file_key=row.file_name,
            reused=True,
        )

    async def _cleanup_cancelled_upload(self, file_key: str) -> None:
        """Finish best-effort cleanup even when disconnect is signalled repeatedly."""
        cleanup = asyncio.create_task(self._delete_uploaded_object(file_key))
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        cleanup.result()

    async def _delete_uploaded_object(self, file_key: str) -> None:
        """Settle a proven unowned object before propagating a disconnect.

        Callers establish absence of metadata or a losing unique-key attempt.
        This is compensation, never an owned Library deletion or a write retry.
        """
        delete = getattr(self.storage, "delete_file", None)
        if not callable(delete):
            return

        async def bounded_delete() -> None:
            try:
                async with asyncio.timeout(30):
                    await delete(file_key=file_key)
            except Exception:
                logger.warning(
                    "uploaded object cleanup failed",
                    extra={"component": "file_storage", "failure_code": "cleanup"},
                )

        cleanup = asyncio.create_task(bounded_delete())
        interrupted = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                interrupted = True
        cleanup.result()
        if interrupted:
            raise asyncio.CancelledError()

    async def get_presigned_url_by_key(
        self, *, file_key: str, expiry_sec: int = 3600, download_name: str | None = None
    ) -> str | None:
        # Duck-typing: only works if storage supports it
        getter = getattr(self.storage, "get_presigned_url", None)
        if callable(getter):
            try:
                if download_name is None:
                    url = await getter(file_key=file_key, expiry_sec=expiry_sec)
                else:
                    url = await getter(
                        file_key=file_key, expiry_sec=expiry_sec, download_name=download_name
                    )
                if not isinstance(url, str) or any(ord(char) < 33 for char in url):
                    raise ValueError("invalid_download_capability")
                parsed = urlsplit(url)
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.port == 0
                ):
                    raise ValueError("invalid_download_capability")
                return url
            except Exception:
                logger.warning(
                    "download capability unavailable",
                    extra={"component": "file_storage", "failure_code": "presign"},
                )
        return None

    async def get_owned_download_url(self, user_id: uuid.UUID, file_id: uuid.UUID) -> str | None:
        """Resolve filename and key together, only from the authenticated owner row."""
        row = await self.repository.fetch_user_file_by_id(user_id, file_id)
        if row is None:
            raise ValueError("File not found")
        return await self.get_presigned_url_by_key(
            file_key=row.file_name, download_name=_legacy_library_filename(row)
        )

    async def require_owned_file_key(self, *, user_id: uuid.UUID, file_key: str) -> str:
        """Resolve legacy downloads only against the authenticated owner's Library."""
        row = await self.repository.fetch_user_file_by_name(user_id, file_key)
        if row is None:
            raise ValueError("owned_file_not_found")
        return str(row.file_name)

    async def get_file_by_key(self, *, file_key: str) -> bytes | None:
        """Get file content by storage key.

        Returns file bytes or None if not supported/found.
        """
        getter = getattr(self.storage, "get_file", None)
        if callable(getter):
            try:
                return await getter(file_key)
            except Exception:
                return None
        return None

    async def get_file_head_by_key(self, *, file_key: str, max_bytes: int) -> bytes | None:
        """Первые ``max_bytes`` байт файла. ``None`` — прочитать не удалось.

        Хранилище без диапазонного чтения обслуживаем обрезкой целого файла: результат
        тот же, цена выше — но молча возвращать «не смогли» из-за реализации хранилища
        нельзя, вердикт о форме файла от неё зависеть не должен.
        """
        try:
            max_bytes = validate_head_limit(max_bytes)
        except ValueError:
            return None
        head_getter = getattr(self.storage, "get_file_head", None)
        if callable(head_getter):
            try:
                return normalize_file_head(await head_getter(file_key, max_bytes), max_bytes)
            except Exception:
                logger.debug(
                    "file head read failed",
                    extra={"component": "file_storage", "failure_code": "read"},
                )
                return None
        whole = await self.get_file_by_key(file_key=file_key)
        return normalize_file_head(whole, max_bytes)

    async def delete(self, user_id: uuid.UUID, file_id: uuid.UUID) -> None:
        guarded_delete = getattr(self.repository, "delete_owned_file_atomically", None)
        if callable(guarded_delete):
            try:
                deleted = await guarded_delete(user_id, file_id, self._delete_owned_objects)
            except Exception:
                raise HTTPException(503, "File is temporarily unavailable") from None
            if not deleted:
                raise HTTPException(404, "File not found")
            return
        try:
            user_file = await self.repository.fetch_user_file_by_id(user_id, file_id)
        except Exception:
            raise HTTPException(503, "File is temporarily unavailable") from None
        if not user_file:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

        # Retain the only retryable reference until storage acknowledges deletion.
        # If the subsequent DB write fails, deleting an already absent object on
        # an explicit retry is idempotent. Never hide an unconfirmed storage delete.
        try:
            await self._delete_owned_objects(user_file)
            await self.repository.delete_file_metadata(user_id=user_id, file_id=file_id)
        except Exception:
            raise HTTPException(503, "File is temporarily unavailable") from None

    async def _delete_owned_objects(self, user_file: UserFile) -> None:
        if getattr(user_file, "upload_intent_id", None) == user_file.id:
            cache = getattr(self, "upload_cache", None)
            if cache is None:
                raise RuntimeError("upload_revocation_unavailable")
            await cache.invalidate("file_upload_admission", str(user_file.id))
        await self.storage.delete_file(file_key=user_file.file_name)

    async def fetch_file_metadata(
        self, user_id: uuid.UUID, file_id: uuid.UUID
    ) -> FileMetadataLogic:
        logger.debug("fetching file metadata", extra={"component": "file_library"})
        user_file = await self.repository.fetch_user_file_by_id(user_id, file_id)
        if not user_file:
            logger.info(
                "file metadata unavailable",
                extra={"component": "file_library", "failure_code": "not_found"},
            )
            raise ValueError("File not found")
        return FileMetadataLogic(
            file_id=user_file.id, file_url=user_file.file_url, file_key=user_file.file_name
        )

    async def presign_upload(
        self, user_id, mode: ServiceType, file_name: str, expiry_sec: int | None = None
    ) -> dict:
        from service.services.files.application.direct_upload import issue

        return await issue(self, user_id, mode, file_name, expiry_sec)

    async def finalize_upload(self, user_id, mode: ServiceType, file_id, file_key: str) -> dict:
        from service.services.files.application.direct_upload import finalize

        return await finalize(self, user_id, mode, file_id, file_key)

    def _generate_file_name(self, file_name: str) -> str:
        masked_file_name = uuid.uuid4().hex + Path(file_name).suffix.lower()
        return masked_file_name
