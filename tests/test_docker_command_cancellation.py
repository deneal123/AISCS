"""Cancellation must settle the CLI process without turning into a successful result."""

import asyncio
import sys
from unittest.mock import AsyncMock

import pytest
from domain.policy import WorkspacePolicy

from drivers import docker_cli
from drivers.base import ContainerRef


def test_sandbox_uses_init_to_reap_cancelled_descendants():
    argv = docker_cli._create_argv("owned-fixture", WorkspacePolicy())
    assert argv.count("--init") == 1


@pytest.mark.parametrize("group_fails", [False, True])
async def test_repeated_cancel_settles_one_cleanup_and_preserves_cancellation(
    monkeypatch, caplog, group_fails
):
    entered = asyncio.Event()
    release = asyncio.Event()
    process = type("Process", (), {"kill": lambda self: None})()
    process.communicate = AsyncMock(return_value=(b"", b""))

    async def group():
        entered.set()
        await release.wait()
        if group_fails:
            raise RuntimeError("private-cleanup-body")

    async def cancelled_request():
        try:
            raise asyncio.CancelledError
        except asyncio.CancelledError:
            await docker_cli._settle_cancelled_process(process, group())
            raise

    task = asyncio.create_task(cancelled_request())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        process.communicate.assert_awaited_once()
        records = [r for r in caplog.records if hasattr(r, "failure_code")]
        assert len(records) == int(group_fails)
        if group_fails:
            assert records[0].failure_code == "process_cleanup_failed"
            assert records[0].exc_info is None
            assert "private-cleanup-body" not in caplog.text
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("operation", ["control", "stdin", "exec"])
async def test_cancel_reaps_real_owned_subprocess(monkeypatch, operation):
    entered = asyncio.Event()
    processes = []
    spawn = asyncio.create_subprocess_exec

    async def fixture_spawn(*_args, **kwargs):
        process = await spawn(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        processes.append(process)
        entered.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fixture_spawn)
    driver = docker_cli.DockerCliDriver()
    stop_group = AsyncMock()
    monkeypatch.setattr(driver, "_kill_process_group", stop_group)
    ref = ContainerRef("docker", "owned-fixture")
    if operation == "control":
        invocation = docker_cli._docker("inspect", "owned-fixture")
    elif operation == "stdin":
        invocation = driver.exec_with_input(
            ref, "fixture", payload=b"fixture", timeout_sec=60, max_output_chars=100
        )
    else:
        invocation = driver.exec(ref, "fixture", timeout_sec=60, max_output_chars=100)
    task = asyncio.create_task(invocation)
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert processes[0].returncode is not None
        if operation == "exec":
            stop_group.assert_awaited_once_with(ref)
        else:
            stop_group.assert_not_awaited()
    finally:
        for process in processes:
            if process.returncode is None:
                process.kill()
            await process.communicate()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
