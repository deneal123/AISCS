"""Причины отказа доступны оператору без сырых логов, модели, сети или Docker."""

import io
import os
import subprocess
import sys
import threading

import pytest

from local_llm.service.infrastructure.llama import runtime
from local_llm.service.infrastructure.llama.diagnostics import (
    MAX_DIAGNOSTIC_BYTES,
    RuntimeDiagnostics,
)


@pytest.mark.parametrize(
    "exit_code,reason",
    [
        (-4, "signal_illegal_instruction"),
        (-6, "signal_aborted"),
        (-9, "signal_killed"),
        (-11, "signal_segmentation_fault"),
        (0, "unexpected_clean_exit"),
        (1, "runtime_exit"),
    ],
)
def test_exit_code_has_closed_reason(exit_code, reason):
    assert RuntimeDiagnostics().reason(exit_code) == reason


@pytest.mark.parametrize(
    "message,reason",
    [
        (b"unknown argument --private", "invalid_arguments"),
        (b"cannot allocate memory: private", "memory_allocation_failed"),
        (b"error while loading shared libraries: private", "shared_library_unavailable"),
        (b"permission denied: private", "runtime_permission_denied"),
        (b"address already in use: private", "runtime_bind_conflict"),
        (b"failed to load model: private", "model_load_failed"),
    ],
)
def test_stderr_is_classified_without_echoing_content(message, reason, capsys):
    diagnostic = RuntimeDiagnostics()
    diagnostic.consume(io.BytesIO(message))
    assert diagnostic.reason(1) == reason
    assert capsys.readouterr() == ("", "")


def test_stderr_capture_is_bounded_and_keeps_the_final_error():
    diagnostic = RuntimeDiagnostics()
    diagnostic.consume(io.BytesIO(b"x" * (MAX_DIAGNOSTIC_BYTES * 20) + b"out of memory"))
    assert len(diagnostic._tail) == MAX_DIAGNOSTIC_BYTES
    assert diagnostic.reason(1) == "memory_allocation_failed"


class WaitingServer:
    def __init__(self):
        self.stopped = threading.Event()
        self.closed = False

    def serve_forever(self, *, poll_interval):
        assert self.stopped.wait(10), "Дочерний процесс не завершил сервер"

    def shutdown(self):
        self.stopped.set()

    def server_close(self):
        self.closed = True


def test_real_child_exit_is_reported_without_private_stderr(monkeypatch, capsys):
    monkeypatch.setattr(runtime.signal, "signal", lambda *_: None)
    server = WaitingServer()
    command = (
        sys.executable,
        "-c",
        "import sys;sys.stderr.write('unknown argument PRIVATE_RUNTIME_DIAGNOSTIC');sys.exit(2)",
    )
    assert runtime.run(server, command, dict(os.environ)) == 1
    output = capsys.readouterr()
    assert server.closed
    assert output.out.strip() == "local_llm_runtime_exited exit_code=2 reason=invalid_arguments"
    assert "PRIVATE_RUNTIME_DIAGNOSTIC" not in output.out + output.err


def test_process_creation_failure_is_reported_without_private_exception(monkeypatch, capsys):
    def unavailable(*args, **kwargs):
        raise OSError("PRIVATE_RUNTIME_DIAGNOSTIC")

    monkeypatch.setattr(runtime.subprocess, "Popen", unavailable)
    server = WaitingServer()
    assert runtime.run(server, ("unused",), {}) == 1
    assert server.closed
    assert capsys.readouterr() == ("local_llm_runtime_unavailable\n", "")


def test_cooperative_stop_is_not_reported_as_a_runtime_crash(monkeypatch, capsys):
    handlers = {}
    monkeypatch.setattr(
        runtime.signal, "signal", lambda number, handler: handlers.update({number: handler})
    )
    server = WaitingServer()

    def serve(*, poll_interval):
        handlers[runtime.signal.SIGTERM](runtime.signal.SIGTERM, None)
        assert server.stopped.wait(10)

    monkeypatch.setattr(server, "serve_forever", serve)
    command = (sys.executable, "-c", "import time;time.sleep(30)")
    assert runtime.run(server, command, dict(os.environ)) == 0
    assert server.closed
    assert capsys.readouterr() == ("", "")


def test_stderr_pipe_is_used_instead_of_publishing_child_output(monkeypatch):
    seen = {}

    def unavailable(*args, **kwargs):
        seen.update(kwargs)
        raise OSError()

    monkeypatch.setattr(runtime.subprocess, "Popen", unavailable)
    assert runtime.run(WaitingServer(), ("unused",), {}) == 1
    assert seen["stdout"] == subprocess.DEVNULL
    assert seen["stderr"] == subprocess.PIPE
