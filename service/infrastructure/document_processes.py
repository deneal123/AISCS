"""Bounded compiler subprocesses with cancellation-safe process ownership."""

from __future__ import annotations

import asyncio
from contextlib import suppress


async def _close(*processes: asyncio.subprocess.Process | None) -> None:
    for process in processes:
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
    await asyncio.gather(
        *(process.wait() for process in processes if process is not None), return_exceptions=True
    )


async def command(*argv: str, timeout: float = 60.0, input_bytes: bytes | None = None):
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if input_bytes is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(input_bytes), timeout=timeout)
        return process.returncode or 0, out
    finally:
        await _close(process)


async def pipe(left: tuple[str, ...], right: tuple[str, ...], *, timeout: float) -> None:
    producer = await asyncio.create_subprocess_exec(
        *left, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    consumer = None
    pending = None
    try:
        assert producer.stdout is not None
        consumer = await asyncio.create_subprocess_exec(
            *right,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert consumer.stdin is not None

        async def forward() -> None:
            try:
                while chunk := await producer.stdout.read(1024 * 1024):
                    consumer.stdin.write(chunk)
                    await consumer.stdin.drain()
            finally:
                consumer.stdin.close()
                await consumer.stdin.wait_closed()

        pending = asyncio.gather(forward(), producer.wait(), consumer.wait())
        # Shield only prevents wait_for from waiting on a backpressured close.
        # Every exit kills/reaps the processes and drains the pending tasks.
        _, producer_code, consumer_code = await asyncio.wait_for(
            asyncio.shield(pending), timeout=timeout
        )
        if producer_code or consumer_code:
            raise TimeoutError
    finally:
        await _close(producer, consumer)
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
