"""Quiescent capture, with one executor-certified pre-GO supervisor exception."""

import os
from uuid import UUID

from infrastructure.ide_bundle_format import BundleFailure


def supervisor_identity(value):
    if value is None:
        return None
    if (
        type(value) is not dict
        or set(value) != {"pid", "start_time", "operation_id"}
        or type(value["pid"]) is not int
        or not 1 < value["pid"] < 2**31
        or type(value["start_time"]) is not str
        or not value["start_time"].isdigit()
        or not 1 <= len(value["start_time"]) <= 32
        or type(value["operation_id"]) is not str
    ):
        raise BundleFailure()
    try:
        if str(UUID(value["operation_id"])) != value["operation_id"]:
            raise ValueError
    except ValueError:
        raise BundleFailure() from None
    return value


def idle(supervisor=None):
    """The exception comes from the driver's unsent Engine session, never a path/argv claim."""
    supervisor = supervisor_identity(supervisor)
    primary, init, seen = 0, False, False
    with os.scandir("/proc") as processes:
        for process in processes:
            if not process.name.isdigit() or int(process.name) == os.getpid():
                continue
            try:
                with open(f"/proc/{process.name}/stat") as source:
                    state = source.read(4096).rpartition(")")[2].split()
                if state[0] == "Z":
                    continue
                with open(f"/proc/{process.name}/cmdline", "rb") as source:
                    argv = source.read(1025).rstrip(b"\0").split(b"\0")
            except FileNotFoundError:
                continue
            if supervisor and int(process.name) == supervisor["pid"]:
                expected = [
                    b"python3",
                    b"-I",
                    b"-S",
                    b"/opt/gpthub-harness/supervisor.py",
                    supervisor["operation_id"].encode(),
                ]
                if len(state) < 20 or state[19] != supervisor["start_time"] or argv != expected:
                    raise BundleFailure("ide_bundle_busy")
                seen = True
            elif (
                process.name == "1"
                and len(argv) == 4
                and argv[0].rsplit(b"/", 1)[-1] in {b"docker-init", b"tini"}
                and argv[1:] == [b"--", b"sleep", b"infinity"]
            ):
                init = True
            elif state[1] == "1" and argv == [b"sleep", b"infinity"]:
                primary += 1
            else:
                raise BundleFailure("ide_bundle_busy")
    if supervisor and not seen:
        raise BundleFailure("ide_bundle_busy")
    if not init or primary != 1:
        raise BundleFailure("ide_bundle_unsupported")
