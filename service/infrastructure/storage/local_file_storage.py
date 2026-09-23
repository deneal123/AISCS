import asyncio
import os
from pathlib import Path
from typing import BinaryIO

from .abstract_file_storage import AbstractFileStorage


class LocalFileStorage(AbstractFileStorage):
    """Простейшее файловое хранилище для пользовательских загрузок.

    Сохраняет файлы в базовую директорию STORAGE_ROOT (env) с ключами вида
    "{folder}/{mode}/{file_name}" и возвращает file_url как абсолютный путь.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        base = base_dir or os.getenv("STORAGE_ROOT", "/var/lib/app/storage")
        self.base_dir = Path(str(base))
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def build_file_path(self, folder: str, mode: str, file_name: str) -> str:
        return f"{folder}/{mode}/{file_name}"

    async def upload_file(self, *, file_key: str, file_data: bytes) -> str:
        path = self.base_dir / file_key

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(file_data)

        # Блокирующий файловый I/O выносим из event loop
        await asyncio.to_thread(_write)
        # Возвращаем абсолютный путь как URL-заменитель; при необходимости заменить на CDN/S3 URL
        return str(path.resolve())

    async def upload_file_stream(self, *, file_key: str, stream: BinaryIO, length: int) -> str:
        path = self.base_dir / file_key

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            stream.seek(0)
            remaining = length
            with path.open("wb") as target:
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise OSError("stream ended before declared length")
                    target.write(chunk)
                    remaining -= len(chunk)

        await asyncio.to_thread(_write)
        return str(path.resolve())

    async def delete_file(self, *, file_key: str) -> None:
        path = self.base_dir / file_key
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def get_file(self, file_key: str) -> bytes:
        """Download file from local storage by key."""
        path = self.base_dir / file_key

        def _read() -> bytes:
            if not path.is_file():
                raise FileNotFoundError(f"File not found: {file_key}")
            return path.read_bytes()

        return await asyncio.to_thread(_read)

    async def get_file_head(self, file_key: str, max_bytes: int) -> bytes:
        """Первые ``max_bytes`` байт файла (для классификации формы вложения)."""
        path = self.base_dir / file_key

        def _read_head() -> bytes:
            if not path.is_file():
                raise FileNotFoundError(f"File not found: {file_key}")
            with path.open("rb") as fh:
                return fh.read(max_bytes)

        return await asyncio.to_thread(_read_head)
