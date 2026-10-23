"""Only a driver's exact pre-GO identity may coexist with a quiescent capture."""

import io
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from infrastructure import ide_idle
from infrastructure.ide_bundle_format import BundleFailure

from drivers.base import ContainerRef, DriverError
from drivers.commands.lifecycle import CommandSession, DockerCommands


def processes(monkeypatch, identity, *, start="555", argv=None, extra=False, missing=False):
    records = {
        1: (0, "1", [b"/sbin/docker-init", b"--", b"sleep", b"infinity"]),
        7: (1, "12", [b"sleep", b"infinity"]),
    }
    if not missing:
        records[20] = (
            0,
            start,
            argv
            or [
                b"python3",
                b"-I",
                b"-S",
                b"/opt/gpthub-harness/supervisor.py",
                identity["operation_id"].encode(),
            ],
        )
    if extra:
        records[30] = (20, "600", [b"python3", b"untrusted.py"])

    @contextmanager
    def scan(path):
        assert path == "/proc"
        yield [SimpleNamespace(name=str(pid)) for pid in records]

    def read(path, mode="r"):
        parent, started, command = records[int(path.split("/")[2])]
        if path.endswith("/stat"):
            return io.StringIO("20 (name) " + " ".join(["S", str(parent)] + ["0"] * 17 + [started]))
        assert mode == "rb"
        return io.BytesIO(b"\0".join(command) + b"\0")

    monkeypatch.setattr(ide_idle.os, "scandir", scan)
    monkeypatch.setattr(ide_idle.os, "getpid", lambda: 999)
    monkeypatch.setattr(ide_idle, "open", read, raising=False)


def test_exact_pre_go_identity_is_allowed_but_generic_capture_stays_strict(monkeypatch):
    identity = {"pid": 20, "start_time": "555", "operation_id": str(uuid4())}
    processes(monkeypatch, identity)
    ide_idle.idle(identity)
    with pytest.raises(BundleFailure, match="ide_bundle_busy"):
        ide_idle.idle()


@pytest.mark.parametrize("change", ["start", "argv", "extra", "missing"])
def test_pid_reuse_forged_command_children_and_missing_identity_block(monkeypatch, change):
    identity = {"pid": 20, "start_time": "555", "operation_id": str(uuid4())}
    options = {
        "start": {"start": "556"},
        "argv": {"argv": [b"python3", b"untrusted.py"]},
        "extra": {"extra": True},
        "missing": {"missing": True},
    }[change]
    processes(monkeypatch, identity, **options)
    with pytest.raises(BundleFailure, match="ide_bundle_busy"):
        ide_idle.idle(identity)


@pytest.mark.parametrize(
    "identity",
    [
        {},
        {"pid": True, "start_time": "1", "operation_id": str(uuid4())},
        {"pid": 20, "start_time": "1", "operation_id": "not-a-uuid"},
        {"pid": 20, "start_time": "1", "operation_id": str(uuid4()), "path": "untrusted.py"},
    ],
)
def test_idle_exception_schema_is_closed(identity):
    with pytest.raises(BundleFailure):
        ide_idle.supervisor_identity(identity)


@pytest.mark.parametrize(
    "running,cache,sent",
    [(False, True, False), (True, False, False), (True, True, True), (True, True, False)],
)
async def test_driver_only_certifies_its_existing_unsent_running_session(running, cache, sent):
    operation = uuid4()
    driver = DockerCommands()
    driver.status = AsyncMock(return_value={"running": running})
    identity = {"pid": 20, "start_time": "555", "operation_id": str(operation)}
    if cache:
        driver.sessions["e" * 64] = CommandSession(None, identity, sent=sent)
    if running and cache and not sent:
        assert (
            await driver.idle_identity(ContainerRef("docker", "c" * 64), operation, "e" * 64)
            == identity
        )
    else:
        with pytest.raises(DriverError, match="command_dispatch_unknown"):
            await driver.idle_identity(ContainerRef("docker", "c" * 64), operation, "e" * 64)
