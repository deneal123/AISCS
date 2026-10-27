"""Bounded transfers to caller-owned streams; cancellation must not outlive I/O."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import BinaryIO

CHUNK_BYTES = 64 * 1024


class DownloadLimitExceeded(ValueError):
    def __init__(self) -> None:
        super().__init__("storage_download_limit_exceeded")


def download_limit(value: int) -> int:
    # The extra byte is an overflow sentinel, including for an empty object.
    if type(value) is not int or not 0 <= value < 2**63 - 1:
        raise ValueError("storage_download_limit_invalid")
    return value


def copy_bounded(source: BinaryIO, target: BinaryIO, max_bytes: int) -> int:
    limit = download_limit(max_bytes)
    copied = 0
    while True:
        requested = min(CHUNK_BYTES, limit - copied + 1)
        chunk = source.read(requested)
        if not isinstance(chunk, bytes) or len(chunk) > requested:
            raise ValueError("storage_download_stream_invalid")
        if not chunk:
            return copied
        if len(chunk) > limit - copied:
            raise DownloadLimitExceeded()
        if target.write(chunk) != len(chunk):
            raise OSError("storage_download_write_incomplete")
        copied += len(chunk)


async def settled_thread[T](operation: Callable[[], T]) -> T:
    """Keep streams open until a cancelled worker has really stopped using them.

    Cancelling ``to_thread`` cannot stop a filesystem/SDK call. Its configured
    transport timeout still owns retirement. Do not retry, close the target or
    start compensation concurrently with that call.
    """
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            # Consume worker failure without logging paths, keys or SDK bodies.
            task.exception()
        raise
