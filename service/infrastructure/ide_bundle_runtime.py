"""Trusted -I capsule worker. Stdin is a framed payload plus a liveness lease.

No repository imports, shell, child processes, PID files, credentials or paths
in output. EOF/invalid heartbeat exits the entire helper, even during blocking
output/materialization. Source is embedded by the private application owner.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import selectors
import signal
import sys
import tempfile
import threading

from infrastructure.ide_bundle_files import capture_bundle, restore_empty
from infrastructure.ide_bundle_format import CHUNK, BundleFailure, BundleLimits
from infrastructure.ide_idle import idle as _idle
from infrastructure.ide_idle import supervisor_identity
from infrastructure.ide_restore_receipt import receipt


def _read_exact(size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = os.read(0, size - len(chunks))
        if not chunk:
            raise BundleFailure()
        chunks.extend(chunk)
    return bytes(chunks)


def _request() -> tuple[dict, BundleLimits]:
    line = bytearray()
    while len(line) <= 8192:
        byte = _read_exact(1)
        if byte == b"\n":
            break
        line.extend(byte)
    else:
        raise BundleFailure()
    request = json.loads(line)
    if (
        type(request) is not dict
        or set(request) - {"ready_receipt", "idle_supervisor"}
        != {"root", "operation", "limits", "input_size", "input_sha256", "timeout"}
        or request["operation"] not in {"capture", "restore", "seal", "receipt"}
        or type(request["limits"]) is not dict
    ):
        raise BundleFailure()
    limits = BundleLimits(**request["limits"])
    supervisor_identity(request.get("idle_supervisor"))
    if "idle_supervisor" in request and request["operation"] != "capture":
        raise BundleFailure()
    proof = request.get("ready_receipt")
    if request["operation"] in {"seal", "receipt"}:
        if (
            request["root"] != "/workspace"
            or type(proof) is not str
            or len(proof) != 64
            or any(c not in "0123456789abcdef" for c in proof)
        ):
            raise BundleFailure()
    elif proof is not None:
        raise BundleFailure()
    expected = request["input_sha256"]
    if request["operation"] == "restore":
        if (
            type(expected) is not str
            or len(expected) != 64
            or any(c not in "0123456789abcdef" for c in expected)
        ):
            raise BundleFailure()
    elif expected is not None:
        raise BundleFailure()
    size, timeout = request["input_size"], request["timeout"]
    if (
        type(size) is not int
        or not 0 <= size <= limits.archive_bytes
        or (request["operation"] != "restore" and size != 0)
        or type(timeout) not in {int, float}
        or not math.isfinite(timeout)
        or not 0 < timeout <= 30
    ):
        raise BundleFailure()
    return request, limits


def _watch(before_exit=None) -> None:
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(0, selectors.EVENT_READ)
            while selector.select(2):
                chunk = os.read(0, CHUNK)
                if not chunk or any(chunk):
                    break
    finally:
        try:
            if before_exit is not None:
                before_exit()
        except BaseException:
            os._exit(75)  # Cleanup is unconfirmed, never a settled acknowledgement.
        os._exit(73)  # Only this helper; no global PGID/kill of another operation.


def _expired(_signum, _frame) -> None:
    raise BundleFailure("ide_bundle_unavailable")


def _report(body: dict) -> None:
    os.write(2, json.dumps(body, separators=(",", ":")).encode())


def main() -> None:
    signal.signal(signal.SIGALRM, _expired)
    signal.setitimer(signal.ITIMER_REAL, 30)
    try:
        request, limits = _request()
        signal.setitimer(signal.ITIMER_REAL, request["timeout"])
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as spool:
            remaining = request["input_size"]
            incoming = hashlib.sha256()
            while remaining:
                chunk = _read_exact(min(CHUNK, remaining))
                spool.write(chunk)
                incoming.update(chunk)
                remaining -= len(chunk)
            if (
                request["operation"] == "restore"
                and incoming.hexdigest() != request["input_sha256"]
            ):
                raise BundleFailure("ide_bundle_changed")
            if _read_exact(1) != b"\x01":
                raise BundleFailure()
            threading.Thread(target=_watch, daemon=True).start()
            if request["operation"] != "receipt":
                _idle(request.get("idle_supervisor"))
            if request["operation"] in {"seal", "receipt"}:
                ready = receipt(request["ready_receipt"], write=request["operation"] == "seal")
                _report(dict(status="ok", operation=request["operation"], ready=ready))
            elif request["operation"] == "capture":
                size = capture_bundle(request["root"], spool, limits)
                spool.seek(0)
                digest = hashlib.sha256()
                while chunk := spool.read(CHUNK):
                    sys.stdout.buffer.write(chunk)
                    digest.update(chunk)
                sys.stdout.buffer.flush()
                _report(
                    dict(status="ok", operation="capture", size=size, sha256=digest.hexdigest())
                )
            else:
                spool.seek(0)
                count = restore_empty(request["root"], spool, limits)
                _report(dict(status="ok", operation="restore", entries=count))
    except BaseException as error:
        code = error.code if isinstance(error, BundleFailure) else "ide_bundle_unavailable"
        try:
            _report(dict(status="error", code=code))
        finally:
            os._exit(65)
    os._exit(0)
