from __future__ import annotations

from typing import BinaryIO, Protocol, runtime_checkable


@runtime_checkable
class MessageBusPort(Protocol):
    async def push(self, queue: str, payload: str) -> None: ...


@runtime_checkable
class FileStoragePort(Protocol):
    def build_file_path(self, folder: str, mode: str, file_name: str) -> str: ...

    async def upload_file(self, *, file_key: str, file_data: bytes) -> str: ...

    async def upload_file_stream(self, *, file_key: str, stream: BinaryIO, length: int) -> str: ...

    async def delete_file(self, *, file_key: str) -> None: ...
