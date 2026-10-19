"""Private bounded binary exchange for a cooperative isolated helper.

Wire: bounded header, exactly input_size bytes, commit byte 1, heartbeat zeroes.
The helper must exit on heartbeat EOF/deadline. Never use this for arbitrary
repository code. No text decoding, shell, payload argv, retry or raw diagnostics.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import math
import tempfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, BinaryIO

CHUNK = 65536


class BinaryExecFailure(Exception):
    def __init__(self, code: str = "binary_exec_unavailable") -> None:
        allowed = {
            "binary_exec_unavailable",
            "binary_exec_input",
            "binary_exec_limit",
            "binary_exec_timeout",
            "binary_exec_cleanup_unknown",
        }
        self.code = code if code in allowed else "binary_exec_unavailable"
        self.settled = False
        super().__init__(self.code)


class BinaryExecCancelled(asyncio.CancelledError):
    def __init__(self) -> None:
        self.settled = False
        super().__init__()


@dataclass(frozen=True, slots=True)
class BinaryExecReply:
    exit_code: int
    source: BinaryIO
    size: int
    sha256: str
    diagnostic: bytes


async def wait_owned[T](task: asyncio.Task[T]) -> T:
    """Do not release a borrowed stream or owned process on repeated cancellation."""
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            interrupted = True
        except Exception:
            break
    if interrupted:
        with contextlib.suppress(BaseException):
            task.result()
        raise asyncio.CancelledError
    return task.result()


async def native_io[T](function: Callable[..., T], *args: Any) -> T:
    return await wait_owned(asyncio.create_task(asyncio.to_thread(function, *args)))


async def _feed(
    process: asyncio.subprocess.Process, header: bytes, source: BinaryIO | None, size: int
) -> None:
    assert process.stdin is not None
    try:
        process.stdin.write(header)
        await process.stdin.drain()
        sent = 0
        if source is not None:
            while chunk := await native_io(source.read, min(CHUNK, size - sent + 1)):
                if not isinstance(chunk, bytes) or len(chunk) > min(CHUNK, size - sent + 1):
                    raise BinaryExecFailure("binary_exec_input")
                sent += len(chunk)
                if sent > size:
                    raise BinaryExecFailure("binary_exec_input")
                process.stdin.write(chunk)
                await process.stdin.drain()
        if sent != size:
            raise BinaryExecFailure("binary_exec_input")
        # Without this byte a partial upload cannot start materialization.
        process.stdin.write(b"\x01")
        await process.stdin.drain()
        while process.returncode is None:
            process.stdin.write(b"\0")
            await process.stdin.drain()
            await asyncio.sleep(0.25)
    except (BrokenPipeError, ConnectionResetError):
        return


async def _receive(stream: asyncio.StreamReader, target: BinaryIO, maximum: int) -> tuple[int, str]:
    size, digest = 0, hashlib.sha256()
    while chunk := await stream.read(CHUNK):
        size += len(chunk)
        if size > maximum:
            raise BinaryExecFailure("binary_exec_limit")
        if await native_io(target.write, chunk) != len(chunk):
            raise BinaryExecFailure()
        digest.update(chunk)
    return size, digest.hexdigest()


async def _diagnostic(stream: asyncio.StreamReader) -> bytes:
    output = bytearray()
    while chunk := await stream.read(CHUNK):
        if len(output) + len(chunk) > 2048:
            raise BinaryExecFailure("binary_exec_limit")
        output.extend(chunk)
    return bytes(output)


async def _discard(stream: asyncio.StreamReader) -> None:
    while await stream.read(CHUNK):
        pass


async def _retire(process: asyncio.subprocess.Process, tasks: list[asyncio.Task]) -> bool:
    """EOF stops the remote watchdog before we ever resort to killing its CLI."""
    try:
        acknowledged = True
        try:
            if process.stdin is not None:
                process.stdin.close()
        except Exception:
            acknowledged = False
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        drains = [
            asyncio.create_task(_discard(stream))
            for stream in (process.stdout, process.stderr)
            if stream is not None
        ]
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            acknowledged = False
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await asyncio.wait_for(process.wait(), 3)
        finally:
            for drain in drains:
                drain.cancel()
            await asyncio.gather(*drains, return_exceptions=True)
        return acknowledged and process.returncode in {0, 65, 73, 74}
    except Exception:
        return False


async def _execute(
    argv: tuple[str, ...],
    header: bytes,
    source: BinaryIO | None,
    input_size: int,
    output: BinaryIO,
    output_limit: int,
    timeout: float,
) -> BinaryExecReply:
    process, tasks, failure = None, [], None
    creation = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    )
    try:
        # Keep the only creation handle if cancellation races OS process creation.
        process = await asyncio.shield(creation)
        assert process.stdout is not None and process.stderr is not None
        tasks = [
            asyncio.create_task(_feed(process, header, source, input_size)),
            asyncio.create_task(_receive(process.stdout, output, output_limit)),
            asyncio.create_task(_diagnostic(process.stderr)),
            asyncio.create_task(process.wait()),
        ]
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout)
        size, digest = results[1]
        return BinaryExecReply(results[3], output, size, digest, results[2])
    except asyncio.CancelledError:
        failure = BinaryExecCancelled()
        raise failure from None
    except TimeoutError:
        failure = BinaryExecFailure("binary_exec_timeout")
        raise failure from None
    except BinaryExecFailure as error:
        failure = error
        raise
    except Exception:
        failure = BinaryExecFailure()
        raise failure from None
    finally:

        async def cleanup() -> bool:
            nonlocal process
            if process is None:
                try:
                    process = await creation
                except Exception:
                    return True  # No process handle was ever created.
            return await _retire(process, tasks)

        cleanup_task = asyncio.create_task(cleanup())
        try:
            settled = await wait_owned(cleanup_task)
        except asyncio.CancelledError:
            if cleanup_task.cancelled():
                raise
            cancelled = (
                failure if isinstance(failure, BinaryExecCancelled) else BinaryExecCancelled()
            )
            cancelled.settled = cleanup_task.result()
            raise cancelled from None
        if failure is not None:
            failure.settled = settled
        elif not settled:
            raise BinaryExecFailure("binary_exec_cleanup_unknown")


@contextlib.asynccontextmanager
async def binary_exchange(
    argv: tuple[str, ...],
    *,
    header: bytes,
    source: BinaryIO | None,
    input_size: int,
    output_limit: int,
    timeout: float,
) -> AsyncIterator[BinaryExecReply]:
    if (
        not isinstance(header, bytes)
        or not 1 <= len(header) <= 8192
        or type(input_size) is not int
        or not 0 <= input_size < 2**31
        or type(output_limit) is not int
        or not 0 <= output_limit < 2**31
        or type(timeout) not in {int, float}
        or not math.isfinite(timeout)
        or not 0 < timeout <= 60
        or (source is None and input_size)
    ):
        raise BinaryExecFailure("binary_exec_input")
    output = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
    try:
        reply = await _execute(argv, header, source, input_size, output, output_limit, timeout)
        await native_io(output.seek, 0)
        yield reply  # Process and all stream workers have settled before exposure.
    finally:
        await native_io(output.close)
