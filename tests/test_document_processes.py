"""Actual subprocesses prove compiler command/pipe cancellation reaps children."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from infrastructure import document_processes

_PIPE_PROBE = """
import asyncio,json,sys
sys.path.insert(0,sys.argv[1])
from infrastructure import document_processes as processes
mode=sys.argv[2]
async def main():
 children=[];original=asyncio.create_subprocess_exec
 async def spawn(*args,**kwargs):
  child=await original(*args,**kwargs);children.append(child);return child
 processes.asyncio.create_subprocess_exec=spawn
 left=(sys.executable,'-c',"import sys;sys.stdout.buffer.write(b'x'*(2*1024*1024))")
 right=(sys.executable,'-c',"import sys;sys.exit(1)" if mode=='reject' else "import time;time.sleep(30)")
 task=asyncio.create_task(processes.pipe(left,right,timeout=.1 if mode=='timeout' else 2))
 if mode=='cancel':
  await asyncio.sleep(.1);task.cancel()
 try: await task
 except asyncio.CancelledError: assert mode=='cancel'
 except TimeoutError: assert mode!='cancel'
 else: raise AssertionError
 assert len(children)==2 and all(child.returncode is not None for child in children)
 print(json.dumps({'status':'passed','reaped':2}))
asyncio.run(main())
"""


@pytest.mark.parametrize("mode", ["reject", "timeout", "cancel"])
def test_pipe_backpressure_cleanup_is_bounded(mode):
    # Isolate the regression so a paused pipe cannot hang the whole pytest run.
    # On the broken path _close already kills both children before hanging in
    # wait(); the private outer timeout terminates only this probe process.
    service = Path(__file__).resolve().parents[1] / "service"
    try:
        result = subprocess.run(
            [sys.executable, "-c", _PIPE_PROBE, str(service), mode],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("pipe_cleanup_timeout", pytrace=False)
    assert result.returncode == 0, "pipe_cleanup_failed"
    assert json.loads(result.stdout) == {"status": "passed", "reaped": 2}


@pytest.mark.asyncio
async def test_pipe_large_success_delivers_all_input():
    producer = (sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*(2*1024*1024))")
    consumer = (
        sys.executable,
        "-c",
        "import sys;assert sys.stdin.buffer.read()==b'x'*(2*1024*1024)",
    )
    await document_processes.pipe(producer, consumer, timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["command", "input", "pipe", "consumer_failure"])
async def test_subprocess_cleanup_on_cancel_or_partial_spawn(monkeypatch, mode):
    original = asyncio.create_subprocess_exec
    processes = []
    entered = asyncio.Event()

    async def spawn(*args, **kwargs):
        if mode == "consumer_failure" and processes:
            raise OSError("private process failure marker")
        process = await original(*args, **kwargs)
        processes.append(process)
        if mode in {"command", "input"} or len(processes) == 2:
            entered.set()
        return process

    monkeypatch.setattr(document_processes.asyncio, "create_subprocess_exec", spawn)
    sleeping = (sys.executable, "-c", "import time; time.sleep(30)")
    coroutine = (
        document_processes.command(
            *sleeping, input_bytes=b"x" * (8 * 1024 * 1024) if mode == "input" else None
        )
        if mode in {"command", "input"}
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


@pytest.mark.asyncio
@pytest.mark.parametrize("output", ["stdout", "stderr"])
async def test_command_rejects_output_over_budget_and_reaps_process(monkeypatch, output):
    original = asyncio.create_subprocess_exec
    processes = []

    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(document_processes.asyncio, "create_subprocess_exec", spawn)
    # Above the intended 1 MiB per-stream ceiling, with a private prefix that
    # must not be included in the failure. The process exits, so the red case
    # is fast and does not rely on a hanging child or a scheduler race.
    script = f"import sys;sys.{output}.buffer.write(b'private-compiler-body'+b'x'*(2*1024*1024))"
    with pytest.raises(ValueError, match="^compiler_output_too_large$"):
        await document_processes.command(sys.executable, "-c", script, timeout=5)
    assert len(processes) == 1 and processes[0].returncode is not None


@pytest.mark.asyncio
async def test_command_drains_both_streams_at_exact_budget_and_feeds_input():
    script = (
        "import sys;data=sys.stdin.buffer.read();"
        "sys.stdout.buffer.write(data);"
        "sys.stderr.buffer.write(b'e'*len(data));sys.exit(7)"
    )
    payload = b"x" * document_processes.COMMAND_OUTPUT_LIMIT
    code, output = await document_processes.command(
        sys.executable, "-c", script, timeout=5, input_bytes=payload
    )
    assert code == 7 and output == payload


@pytest.mark.asyncio
async def test_command_timeout_reaps_child(monkeypatch):
    original = asyncio.create_subprocess_exec
    processes = []

    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(document_processes.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(TimeoutError):
        await document_processes.command(
            sys.executable, "-c", "import time;time.sleep(30)", timeout=0.05
        )
    assert len(processes) == 1 and processes[0].returncode is not None


@pytest.mark.asyncio
async def test_compiler_maps_output_overflow_to_bounded_failure(monkeypatch):
    from infrastructure import document_compiler

    async def overflow(*args, **kwargs):
        raise document_processes.CommandOutputLimit("private-compiler-body")

    monkeypatch.setattr(document_processes, "command", overflow)
    with pytest.raises(document_compiler.CompilerFailure, match="^runtime_unavailable$") as caught:
        await document_compiler._command("docker", "inspect")
    assert caught.value.__suppress_context__
