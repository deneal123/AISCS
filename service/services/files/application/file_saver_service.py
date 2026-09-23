import base64
import hashlib
import logging
import re
import tempfile
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, status

from service.models.db.db_models import UserFile
from service.models.file_models import FileMetadataLogic
from service.models.key_value import ServiceType
from service.services.files.application.dto import (
    FetchUserFilesResponse,
    FileMetadata,
    UploadResponse,
)
from service.services.files.application.ports.interfaces import FileStoragePort, MessageBusPort
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
    ) -> None:
        if file_storage is None:
            raise ValueError("file_storage is required for FileSaverService")
        self.storage = file_storage
        self.message_bus = message_bus
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
        self, user_id: uuid.UUID, *, limit: int = 200, offset: int = 0, cursor: str = ""
    ) -> dict:
        """Return safe metadata for persistent chat files.

        Workspace consumers must never infer a library from historic chat
        metadata: attachment rows contain no stable file identity and can
        outlive the underlying object.  The file repository is authoritative.
        """
        page_size = max(1, min(int(limit), 500))
        before = self._decode_cursor(cursor)
        page_options = {"limit": page_size + 1, "offset": max(0, int(offset))}
        if before is not None:
            page_options["before"] = before
        rows = await self.repository.fetch_user_files_metadata(
            user_id, ServiceType.CHAT, **page_options
        )
        items: list[dict] = []
        for row in rows[:page_size]:
            items.append(
                {
                    "file_id": str(row.id),
                    "name": _legacy_library_filename(row),
                    "file_type": ServiceType.CHAT.value,
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

        file_url = await self.storage.upload_file(
            file_key=file_key,
            file_data=file_content,
        )

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
            # A successfully uploaded object without its owner-bound metadata
            # is neither visible in Library nor safely importable.  Best-effort
            # cleanup prevents turning a failed chat attachment into an orphan.
            await self._delete_uploaded_object(file_key)
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
    ) -> UploadResponse:
        """Persist a generated artifact with bounded disk spooling and integrity checks."""

        safe_name = str(file_name or "").strip() or None
        expected_size = int(expected_size)
        expected_sha256 = str(expected_sha256 or "").lower()
        if (
            expected_size < 1
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
                if not isinstance(chunk, bytes) or not chunk:
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
            file_url = await uploader(file_key=file_key, stream=spool, length=size)

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
        except RepositoryIntegrityError:
            await self._delete_uploaded_object(file_key)
            existing = await self.repository.fetch_user_file_by_upload_intent(
                user_id, upload_intent_id
            )
            if existing is None:
                raise
            return self._reused_upload(existing, safe_name, expected_sha256)
        except Exception:
            await self._delete_uploaded_object(file_key)
            raise
        return UploadResponse(file_id=saved_metadata.id, file_url=file_url, file_key=file_key)

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

    async def _delete_uploaded_object(self, file_key: str) -> None:
        delete = getattr(self.storage, "delete_file", None)
        if not callable(delete):
            return
        try:
            await delete(file_key=file_key)
        except Exception:
            logger.warning(
                "uploaded object cleanup failed",
                extra={"component": "file_storage", "failure_code": "cleanup"},
            )

    async def get_presigned_url_by_key(
        self, *, file_key: str, expiry_sec: int = 3600
    ) -> str | None:
        # Duck-typing: only works if storage supports it
        getter = getattr(self.storage, "get_presigned_url", None)
        if callable(getter):
            return await getter(file_key=file_key, expiry_sec=expiry_sec)
        return None

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
        head_getter = getattr(self.storage, "get_file_head", None)
        if callable(head_getter):
            try:
                return await head_getter(file_key, max_bytes)
            except Exception:
                logger.debug(
                    "file head read failed",
                    extra={"component": "file_storage", "failure_code": "read"},
                )
                return None
        whole = await self.get_file_by_key(file_key=file_key)
        return None if whole is None else whole[:max_bytes]

    async def delete(self, user_id: uuid.UUID, file_id: uuid.UUID) -> None:
        user_file = await self.repository.fetch_user_file_by_id(user_id, file_id)
        if not user_file:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

        await self.repository.delete_file_metadata(user_id=user_id, file_id=file_id)
        storage_file_key = user_file.file_name
        await self.storage.delete_file(file_key=storage_file_key)

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
        """Prepare a presigned upload URL and return temporary identifiers.

        Does not persist metadata; client must call callback to finalize.
        """
        import uuid

        masked_file_name = self._generate_file_name(file_name)
        file_key = self.storage.build_file_path(self.folder, mode.value, masked_file_name)
        # Generate presigned upload URL if storage supports it
        getter = getattr(self.storage, "get_presigned_upload_url", None)
        upload_url = None
        if callable(getter):
            try:
                upload_url = await getter(file_key=file_key, expiry_sec=expiry_sec)
            except Exception:
                logger.warning(
                    "presigned upload unavailable",
                    extra={"component": "file_storage", "failure_code": "presign"},
                )
                upload_url = None
        # return temporary id (caller to persist on callback)
        return {"file_id": uuid.uuid4(), "file_key": file_key, "upload_url": upload_url}

    async def finalize_upload(self, user_id, mode: ServiceType, file_id, file_key: str) -> dict:
        """Persist metadata after upload completion and return stored metadata."""
        # Determine public URL: prefer presigned download URL, fallback to storage path
        download_getter = getattr(self.storage, "get_presigned_url", None)
        if callable(download_getter):
            try:
                file_url = await download_getter(file_key=file_key)
            except Exception:
                logger.warning(
                    "presigned download unavailable",
                    extra={"component": "file_storage", "failure_code": "presign"},
                )
                file_url = file_key
        else:
            # Fallback to raw file key or local path
            file_url = file_key

        file_metadata = UserFile(user_id=user_id, type=mode, file_name=file_key, file_url=file_url)
        saved = await self.repository.add_file_metadata(file_metadata)
        if self.message_bus is not None:
            try:
                await self.message_bus.push("file:scan:queue", saved.file_name)
            except Exception:
                logger.debug(
                    "file scan enqueue failed",
                    extra={"component": "file_scan", "failure_code": "transport"},
                )

        return {"file_id": saved.id, "file_url": saved.file_url}

    def _generate_file_name(self, file_name: str) -> str:
        masked_file_name = uuid.uuid4().hex + Path(file_name).suffix.lower()
        return masked_file_name
