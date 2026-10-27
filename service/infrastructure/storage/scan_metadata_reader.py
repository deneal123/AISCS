"""Bounded metadata hashing; cancellation stops after the in-flight SDK read."""

import asyncio
import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from threading import Event
from typing import Protocol

SCAN_READ_CHUNK = 1024 * 1024


class ScanStream(Protocol):
    def read(self, amount: int) -> bytes: ...


def _consume(task: asyncio.Task) -> None:
    try:
        task.result()
    except (asyncio.CancelledError, Exception):
        pass


async def read_scan_metadata(
    open_stream: Callable[[], AbstractContextManager[ScanStream]],
) -> dict:
    stop = Event()

    def read() -> dict:
        digest = hashlib.sha256()
        size = 0
        if stop.is_set():
            raise RuntimeError("scan_read_cancelled")
        with open_stream() as stream:
            while not stop.is_set():
                chunk = stream.read(SCAN_READ_CHUNK)
                if not isinstance(chunk, bytes) or len(chunk) > SCAN_READ_CHUNK:
                    raise ValueError("scan_content_invalid")
                if not chunk:
                    return {"status": "ok", "size": size, "sha256": digest.hexdigest()}
                size += len(chunk)
                digest.update(chunk)
        raise RuntimeError("scan_read_cancelled")

    task = asyncio.create_task(asyncio.to_thread(read))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Do not close a response concurrently with its blocking read. Its owner
        # closes/releases it when that read returns; no later chunk is started.
        stop.set()
        task.add_done_callback(_consume)
        raise
