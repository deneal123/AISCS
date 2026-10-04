"""Actual subprocesses prove compiler command/pipe cancellation reaps children."""

import asyncio
import sys

import pytest
from infrastructure import document_processes


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["command", "pipe", "consumer_failure"])
async def test_subprocess_cleanup_on_cancel_or_partial_spawn(monkeypatch, mode):
    original = asyncio.create_subprocess_exec
    processes = []
    entered = asyncio.Event()

    async def spawn(*args, **kwargs):
        if mode == "consumer_failure" and processes:
            raise OSError("private process failure marker")
        process = await original(*args, **kwargs)
        processes.append(process)
        if mode == "command" or len(processes) == 2:
            entered.set()
        return process

    monkeypatch.setattr(document_processes.asyncio, "create_subprocess_exec", spawn)
    sleeping = (sys.executable, "-c", "import time; time.sleep(30)")
    coroutine = (
        document_processes.command(*sleeping)
        if mode == "command"
        else document_processes.pipe(sleeping, sleeping, timeout=60)
    )
    task = asyncio.create_task(coroutine)
    try:
        if mode == "consumer_failure":
            with pytest.raises(OSError):
                await asyncio.wait_for(task, 5)
        else:
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
        assert len(processes) == (2 if mode == "pipe" else 1)
        assert all(process.returncode is not None for process in processes)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for process in processes:
            if process.returncode is None:
                process.kill()
                await process.wait()
