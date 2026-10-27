from __future__ import annotations

from typing import BinaryIO, Protocol


class AbstractFileStorage(Protocol):
    """Простой контракт для бэкендов хранения файлов."""

    @property
    def namespace_id(self) -> str:
        """Stable locator fingerprint, not credentials or a routable capability."""
        ...

    def build_file_path(
        self, folder: str, mode: str, file_name: str
    ) -> str:  # pragma: no cover - trivial
        ...

    async def upload_file(self, *, file_key: str, file_data: bytes) -> str: ...

    async def upload_file_stream(self, *, file_key: str, stream: BinaryIO, length: int) -> str:
        """Settle all worker/SDK I/O before returning or propagating cancellation.

        Callers use this boundary to record writer quiescence. No retry or late
        commit may remain active after this method returns/raises.
        """
        ...

    async def download_file_stream(self, *, file_key: str, target: BinaryIO, max_bytes: int) -> int:
        """Append at most max_bytes; reject overflow, never return a partial success.

        The caller owns the target and discards it on failure. Cancellation only
        returns after the exact worker has stopped accessing it.
        """
        ...

    async def delete_file(self, *, file_key: str) -> None: ...
