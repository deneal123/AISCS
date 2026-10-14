"""Bounded compiler subprocesses with cancellation-safe process ownership."""

from __future__ import annotations

import asyncio
from contextlib import suppress

COMMAND_OUTPUT_LIMIT = 1024 * 1024


class CommandOutputLimit(ValueError):
    """Private subprocess output exceeded the fixed capture budget."""


async def _read_output(stream: asyncio.StreamReader, *, retain: bool) -> bytes:
    captured = bytearray()
    size = 0
    while chunk := await stream.read(65536):
        size += len(chunk)
        if size > COMMAND_OUTPUT_LIMIT:
            raise CommandOutputLimit("compiler_output_too_large")
        if retain:
            captured.extend(chunk)
    return bytes(captured)


async def _feed_input(process: asyncio.subprocess.Process, data: bytes | None) -> None:
    if data is None:
        return
    assert process.stdin is not None
    try:
        for start in range(0, len(data), 65536):
            process.stdin.write(data[start : start + 65536])
            await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        process.stdin.close()
        # Process ownership handles closure/reaping. Waiting for a backpressured
        # stdin here would delay cancellation before the child can be killed.


async def _discard_output(stream: asyncio.StreamReader) -> None:
    while await stream.read(65536):
        pass


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
    assert process.stdout is not None and process.stderr is not None
    tasks = [
        asyncio.create_task(_read_output(process.stdout, retain=True)),
        asyncio.create_task(_read_output(process.stderr, retain=False)),
        asyncio.create_task(_feed_input(process, input_bytes)),
        asyncio.create_task(process.wait()),
    ]
    pending = asyncio.gather(*tasks)
    try:
        out, _, _, _ = await asyncio.wait_for(asyncio.shield(pending), timeout=timeout)
        return process.returncode or 0, out
    finally:
        pending.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(pending, *tasks, return_exceptions=True)
        # Reap and drain together: Process.wait() can otherwise remain blocked
        # by a paused pipe transport after a reader exceeded its budget.
        await asyncio.gather(
            _close(process), _discard_output(process.stdout), _discard_output(process.stderr)
        )


async def pipe(left: tuple[str, ...], right: tuple[str, ...], *, timeout: float) -> None:
    producer = await asyncio.create_subprocess_exec(
        *left, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    consumer = None
    pending = None
    tasks = []
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
                while chunk := await producer.stdout.read(65536):
                    consumer.stdin.write(chunk)
                    await consumer.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                raise TimeoutError from None
            finally:
                consumer.stdin.close()

        tasks = [
            asyncio.create_task(forward()),
            asyncio.create_task(producer.wait()),
            asyncio.create_task(consumer.wait()),
        ]
        pending = asyncio.gather(*tasks)
        # Shield only prevents wait_for from waiting on a backpressured close.
        # Every exit kills/reaps the processes and drains the pending tasks.
        _, producer_code, consumer_code = await asyncio.wait_for(
            asyncio.shield(pending), timeout=timeout
        )
        if producer_code or consumer_code:
            raise TimeoutError
    finally:
        if pending is not None:
            pending.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        assert producer.stdout is not None
        await asyncio.gather(_close(producer, consumer), _discard_output(producer.stdout))
