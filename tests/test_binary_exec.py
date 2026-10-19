"""Real pipe/process tests for the bounded cooperative binary transport."""

import asyncio
import hashlib
import io
import json
import sys
import threading

import pytest

from drivers import binary_exec
from drivers.binary_exec import BinaryExecCancelled, BinaryExecFailure, binary_exchange

WORKER = r"""
import json,os,sys,threading,time
try:
    request=json.loads(sys.stdin.buffer.readline())
    body=sys.stdin.buffer.read(request['size'])
    if len(body)!=request['size'] or sys.stdin.buffer.read(1)!=b'\x01':
        raise ValueError()
except Exception:
    os._exit(65)
def watch():
    while sys.stdin.buffer.read(1)==b'\0': pass
    os._exit(73)
threading.Thread(target=watch,daemon=True).start()
if request.get('ready'):
    open(request['ready'],'wb').close()
mode=request['mode']
if mode=='hold':
    while not request.get('stop') or not os.path.exists(request['stop']): time.sleep(.01)
elif mode=='stdout_flood':
    sys.stdout.buffer.write(b'x'*(1024*1024));sys.stdout.buffer.flush()
elif mode=='stderr_flood':
    sys.stderr.buffer.write(b'x'*(1024*1024));sys.stderr.buffer.flush()
elif mode=='error':
    sys.stderr.buffer.write(b'PRIVATE_ERROR_BODY');sys.stderr.buffer.flush();os._exit(65)
sys.stdout.buffer.write(body);sys.stdout.buffer.flush()
sys.stderr.buffer.write(b'{}');sys.stderr.buffer.flush()
os._exit(0)
"""


def exchange(body=b"", mode="echo", size=None, maximum=4 * 1024 * 1024, timeout=3, **extra):
    declared = len(body) if size is None else size
    header = json.dumps(dict(mode=mode, size=declared, **extra)).encode() + b"\n"
    return binary_exchange(
        (sys.executable, "-I", "-c", WORKER),
        header=header,
        source=io.BytesIO(body),
        input_size=declared,
        output_limit=maximum,
        timeout=timeout,
    )


def observe_processes(monkeypatch):
    original, processes, arguments = asyncio.create_subprocess_exec, [], []

    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        arguments.append(args)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return processes, arguments


async def ready(path):
    async with asyncio.timeout(5):
        while not path.exists():
            await asyncio.sleep(0.01)


async def test_binary_roundtrip_spools_and_closes_only_after_consumption(monkeypatch):
    processes, argv = observe_processes(monkeypatch)
    body = b"\x00\xffBINARY_SOURCE" * 150000
    async with exchange(body, timeout=10) as reply:
        output = reply.source
        assert reply.exit_code == 0 and reply.size == len(body)
        assert reply.sha256 == hashlib.sha256(body).hexdigest()
        assert output.read() == body
        assert output._rolled and not output.closed
        assert all("BINARY_SOURCE" not in str(arg) for arg in argv[0])
        assert processes[0].returncode == 0
    assert output.closed


@pytest.mark.parametrize("delta", [-1, 1])
async def test_mismatched_input_never_sends_commit_byte(delta):
    with pytest.raises(BinaryExecFailure, match="binary_exec_input") as caught:
        async with exchange(b"abc", size=3 + delta):
            pytest.fail("invalid input accepted")
    assert caught.value.settled


@pytest.mark.parametrize("mode", ["stdout_flood", "stderr_flood"])
async def test_output_budget_aborts_remote_worker_without_retaining_excess(monkeypatch, mode):
    processes, _ = observe_processes(monkeypatch)
    with pytest.raises(BinaryExecFailure, match="binary_exec_limit") as caught:
        async with exchange(mode=mode, maximum=128):
            pytest.fail("oversized output accepted")
    assert caught.value.settled and processes[0].returncode in {0, 73}


async def test_nonzero_exit_retains_only_private_bounded_diagnostic():
    async with exchange(mode="error") as reply:
        assert reply.exit_code == 65
        assert reply.diagnostic == b"PRIVATE_ERROR_BODY"
        assert reply.size == 0


async def test_timeout_waits_for_worker_eof_ack(monkeypatch, tmp_path):
    processes, _ = observe_processes(monkeypatch)
    with pytest.raises(BinaryExecFailure, match="binary_exec_timeout") as caught:
        async with exchange(mode="hold", ready=str(tmp_path / "ready"), timeout=0.5):
            pytest.fail("timeout accepted")
    assert caught.value.settled and processes[0].returncode == 73


async def test_cli_failure_is_not_proof_of_remote_helper_termination():
    with pytest.raises(BinaryExecFailure, match="binary_exec_cleanup_unknown") as caught:
        async with binary_exchange(
            (sys.executable, "-I", "-c", "raise SystemExit(1)"),
            header=b"{}\n",
            source=None,
            input_size=0,
            output_limit=1,
            timeout=2,
        ):
            pass
    assert not caught.value.settled


async def test_repeated_cancel_keeps_the_acknowledged_exit_evidence(monkeypatch, tmp_path):
    original = binary_exec._retire
    entered, release = asyncio.Event(), asyncio.Event()

    async def gated(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(binary_exec, "_retire", gated)

    async def invoke():
        async with exchange(mode="hold", ready=str(tmp_path / "ready"), timeout=10):
            pass

    task = asyncio.create_task(invoke())
    try:
        await ready(tmp_path / "ready")
        task.cancel()
        await asyncio.wait_for(entered.wait(), 3)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        release.set()
        with pytest.raises(BinaryExecCancelled) as caught:
            await task
        assert caught.value.settled
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancellation_stops_only_its_worker_not_a_sibling(monkeypatch, tmp_path):
    processes, _ = observe_processes(monkeypatch)

    async def run(name, stop=None):
        async with exchange(mode="hold", ready=str(tmp_path / name), stop=stop, timeout=10):
            pass

    first = asyncio.create_task(run("first"))
    second = asyncio.create_task(run("second", str(tmp_path / "stop")))
    try:
        await ready(tmp_path / "first")
        await ready(tmp_path / "second")
        first.cancel()
        with pytest.raises(BinaryExecCancelled) as caught:
            await first
        assert caught.value.settled
        assert processes[0].returncode == 73 and processes[1].returncode is None
        (tmp_path / "stop").touch()
        await second
        assert processes[1].returncode == 0
    finally:
        for task in (first, second):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


async def test_cancel_during_spawn_settles_the_only_creation_handle(monkeypatch):
    original = asyncio.create_subprocess_exec
    entered, release, processes = asyncio.Event(), asyncio.Event(), []

    async def delayed(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        entered.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)

    async def invoke():
        async with exchange():
            pass

    task = asyncio.create_task(invoke())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(BinaryExecCancelled) as caught:
            await task
        assert caught.value.settled and len(processes) == 1
        assert processes[0].returncode == 65
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_repeated_cancel_waits_for_native_stream_borrow(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class Reader(io.BytesIO):
        def read(self, count=-1):
            entered.set()
            release.wait(5)
            return super().read(count)

    source = Reader(b"a")

    async def invoke():
        async with binary_exchange(
            (sys.executable, "-I", "-c", WORKER),
            header=b'{"mode":"echo","size":1}\n',
            source=source,
            input_size=1,
            output_limit=2,
            timeout=5,
        ):
            pass

    task = asyncio.create_task(invoke())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not source.closed
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not source.closed  # caller owns the borrowed input
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        source.close()


@pytest.mark.parametrize(
    "kwargs",
    [{"input_size": True}, {"output_limit": -1}, {"timeout": float("nan")}, {"header": b""}],
)
async def test_invalid_budgets_never_spawn(monkeypatch, kwargs):
    processes, _ = observe_processes(monkeypatch)
    arguments = dict(header=b"{}\n", source=None, input_size=0, output_limit=1, timeout=1)
    arguments.update(kwargs)
    with pytest.raises(BinaryExecFailure, match="binary_exec_input"):
        async with binary_exchange((sys.executable, "-c", ""), **arguments):
            pass
    assert processes == []
