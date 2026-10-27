import asyncio
import os
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import BinaryIO

from service.services.files.domain.file_read_limits import validate_head_limit

from .abstract_file_storage import AbstractFileStorage
from .bounded_download import copy_bounded, download_limit, settled_thread
from .identity import storage_identity
from .scan_metadata_reader import read_scan_metadata
from .stream_upload_contract import validate_upload_chunk, validate_upload_length


async def _settle_local_write(write: Callable[[], None]) -> None:
    """Keep caller-owned streams alive until the exact OS writer has exited.

    Thread cancellation cannot stop filesystem I/O. Compensation must follow
    completion, never race it. A disconnect remains cancellation even if the
    writer subsequently fails; its exception is consumed, not logged raw.
    """
    task = asyncio.create_task(asyncio.to_thread(write))
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
        if not task.cancelled():
            try:
                task.result()
            except Exception:
                pass
        raise


class LocalFileStorage(AbstractFileStorage):
    """Простейшее файловое хранилище для пользовательских загрузок.

    Сохраняет файлы в базовую директорию STORAGE_ROOT (env) с ключами вида
    "{folder}/{mode}/{file_name}" и возвращает file_url как абсолютный путь.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        base = base_dir or os.getenv("STORAGE_ROOT", "/var/lib/app/storage")
        self.base_dir = Path(str(base)).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def build_file_path(self, folder: str, mode: str, file_name: str) -> str:
        return f"{folder}/{mode}/{file_name}"

    @property
    def namespace_id(self) -> str:
        return storage_identity("local", os.path.normcase(str(self.base_dir)))

    def _path(self, file_key: str) -> Path:
        if (
            not isinstance(file_key, str)
            or not file_key
            or file_key.startswith("/")
            or PureWindowsPath(file_key).drive
            or any(c in file_key for c in "\\:")
            or any(ord(c) < 32 or ord(c) == 127 for c in file_key)
            or any(part in {"", ".", ".."} for part in file_key.split("/"))
        ):
            raise ValueError("storage_key_invalid")
        path = self.base_dir
        try:
            for part in file_key.split("/"):
                path /= part
                if path.is_symlink() or path.is_junction():
                    raise ValueError("storage_key_invalid")
            if not path.resolve().is_relative_to(self.base_dir):
                raise ValueError("storage_key_invalid")
        except (OSError, RuntimeError):
            raise ValueError("storage_key_invalid") from None
        return path

    async def upload_file(self, *, file_key: str, file_data: bytes) -> str:
        path = self._path(file_key)

        def _write() -> None:
            path = self._path(file_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._path(file_key).write_bytes(file_data)

        # Блокирующий файловый I/O выносим из event loop
        await _settle_local_write(_write)
        # Возвращаем абсолютный путь как URL-заменитель; при необходимости заменить на CDN/S3 URL
        return str(path.resolve())

    async def upload_file_stream(self, *, file_key: str, stream: BinaryIO, length: int) -> str:
        length = validate_upload_length(length)
        path = self._path(file_key)

        def _write() -> None:
            path = self._path(file_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            stream.seek(0)
            remaining = length
            with self._path(file_key).open("wb") as target:
                while remaining:
                    requested = min(1024 * 1024, remaining)
                    chunk = validate_upload_chunk(stream.read(requested), requested)
                    target.write(chunk)
                    remaining -= len(chunk)

        await _settle_local_write(_write)
        return str(path.resolve())

    async def delete_file(self, *, file_key: str) -> None:
        await asyncio.to_thread(lambda: self._path(file_key).unlink(missing_ok=True))

    async def download_file_stream(self, *, file_key: str, target: BinaryIO, max_bytes: int) -> int:
        limit = download_limit(max_bytes)

        def read() -> int:
            with self._path(file_key).open("rb") as source:
                return copy_bounded(source, target, limit)

        return await settled_thread(read)

    async def read_file_metadata(self, file_key: str) -> dict:
        return await read_scan_metadata(lambda: self._path(file_key).open("rb"))

    async def get_file(self, file_key: str) -> bytes:
        """Download file from local storage by key."""

        def _read() -> bytes:
            path = self._path(file_key)
            if not path.is_file():
                raise FileNotFoundError("storage_file_missing")
            return path.read_bytes()

        return await asyncio.to_thread(_read)

    async def get_file_head(self, file_key: str, max_bytes: int) -> bytes:
        """Первые ``max_bytes`` байт файла (для классификации формы вложения)."""
        max_bytes = validate_head_limit(max_bytes)

        def _read_head() -> bytes:
            path = self._path(file_key)
            if not path.is_file():
                raise FileNotFoundError("storage_file_missing")
            with path.open("rb") as fh:
                return fh.read(max_bytes)

        return await asyncio.to_thread(_read_head)
