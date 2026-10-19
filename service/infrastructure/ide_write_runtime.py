"""Atomic text writes and opaque create-only imports, without code execution or Git snapshots."""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import secrets
import signal
import stat
import threading
import time

from infrastructure.ide_bundle_runtime import _idle, _read_exact, _report, _watch
from infrastructure.ide_read_runtime import (
    MAX_BYTES,
    ReadFailure,
    components,
    open_directory,
    read_file,
    snapshot_info,
)

_scratch_lock = threading.RLock()
_scratch = None
MAX_IMPORT_BYTES = 20 * 1024 * 1024


def _cleanup_scratch():
    global _scratch
    with _scratch_lock:
        if _scratch is None:
            return
        parent, name, identity = _scratch
        _scratch = None
        try:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == identity:
                os.unlink(name, dir_fd=parent)
        except FileNotFoundError:
            pass
        finally:
            os.close(parent)


def _alive(deadline):
    if time.time() >= deadline:
        raise ReadFailure("ide_runtime_expired")


def commit(root, path, operation, content, expected_digest, deadline):
    global _scratch
    parts = components(path)
    if operation not in {"file", "directory", "import"}:
        raise ReadFailure("invalid_request")
    if len(content) > (MAX_IMPORT_BYTES if operation == "import" else MAX_BYTES):
        raise ReadFailure("ide_write_limit")
    if operation == "import":
        # Library bytes are opaque, create-only and never unpacked or executable.
        if expected_digest is not None:
            raise ReadFailure("invalid_request")
    else:
        try:
            content.decode("utf-8")
        except UnicodeError:
            raise ReadFailure("ide_file_unsupported") from None
        if b"\0" in content:
            raise ReadFailure("ide_file_unsupported")
    if operation == "directory" and (content or expected_digest is not None):
        raise ReadFailure("invalid_request")
    if expected_digest is not None and (
        type(expected_digest) is not str
        or len(expected_digest) != 64
        or any(char not in "0123456789abcdef" for char in expected_digest)
    ):
        raise ReadFailure("invalid_request")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    parent, temporary = None, None
    try:
        parent = open_directory(root_fd, parts[:-1])
        if os.fstat(parent).st_dev != os.fstat(root_fd).st_dev:
            raise ReadFailure("ide_path_forbidden")
        _alive(deadline)
        if operation == "directory":
            os.mkdir(parts[-1], 0o755, dir_fd=parent)
            os.fsync(parent)
            return dict(written=True, path=path, kind="dir", digest=None, size=0)
        try:
            before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            before = None
        if expected_digest is None:
            if before is not None:
                raise ReadFailure("ide_file_changed")
        else:
            if before is None:
                raise ReadFailure("ide_file_changed")
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_mode & 0o7000
                or before.st_uid != os.geteuid()
            ):
                raise ReadFailure("ide_file_unsupported")
            current = read_file(root_fd, path)
            if current["kind"] != "text" or current["truncated"]:
                raise ReadFailure("ide_file_unsupported")
            if current["digest"] != expected_digest:
                raise ReadFailure("ide_file_changed")
        temporary = ".gpthub-write-" + secrets.token_hex(16)
        with _scratch_lock:
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            identity = os.fstat(fd)
            _scratch = (os.dup(parent), temporary, (identity.st_dev, identity.st_ino))
        try:
            remaining = memoryview(content)
            while remaining:
                count = os.write(fd, remaining)
                if count <= 0:
                    raise OSError("short_write")
                remaining = remaining[count:]
            os.fchmod(fd, stat.S_IMODE(before.st_mode) if before else 0o644)
            os.fsync(fd)
        finally:
            os.close(fd)
        # Refuse publication if an ancestor was replaced while staging bytes.
        check = open_directory(root_fd, parts[:-1])
        try:
            if snapshot_info(os.fstat(check))[:2] != snapshot_info(os.fstat(parent))[:2]:
                raise ReadFailure("ide_file_changed")
        finally:
            os.close(check)
        _alive(deadline)
        if before is None:
            # Atomic no-clobber publication, including a racing existing symlink.
            os.link(
                temporary, parts[-1], src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False
            )
        else:
            latest = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            if snapshot_info(before) != snapshot_info(latest):
                raise ReadFailure("ide_file_changed")
            os.replace(temporary, parts[-1], src_dir_fd=parent, dst_dir_fd=parent)
            temporary = None
        os.fsync(parent)
        return dict(
            written=True,
            path=path,
            kind="file",
            digest=hashlib.sha256(content).hexdigest(),
            size=len(content),
        )
    finally:
        _cleanup_scratch()
        if parent is not None:
            os.close(parent)
        os.close(root_fd)


def execute(request, content):
    try:
        return commit(
            request["root"],
            request["path"],
            request["operation"],
            content,
            request["expected_digest"],
            request["deadline"],
        )
    except ReadFailure as error:
        return {"error": error.code}
    except OSError as error:
        code = "ide_write_unconfirmed"
        if error.errno == errno.EEXIST:
            code = "ide_file_changed"
        elif error.errno in {errno.ELOOP, errno.ENOTDIR, errno.EPERM, errno.EACCES}:
            code = "ide_path_forbidden"
        elif error.errno == errno.ENOENT:
            code = "ide_file_missing"
        return {"error": code}


def main():
    def expired(_signum, _frame):
        raise ReadFailure("ide_write_unconfirmed")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 10)
    try:
        header = bytearray()
        while len(header) <= 8192:
            char = _read_exact(1)
            if char == b"\n":
                break
            header.extend(char)
        else:
            raise ReadFailure("invalid_request")
        request = json.loads(header)
        if (
            type(request) is not dict
            or set(request)
            != {
                "root",
                "path",
                "operation",
                "expected_digest",
                "deadline",
                "input_size",
                "input_sha256",
            }
            or type(request["input_size"]) is not int
            or not 0
            <= request["input_size"]
            <= (MAX_IMPORT_BYTES if request.get("operation") == "import" else MAX_BYTES)
            or type(request["deadline"]) not in {int, float}
            or not math.isfinite(request["deadline"])
        ):
            raise ReadFailure("invalid_request")
        content = _read_exact(request["input_size"])
        if (
            hashlib.sha256(content).hexdigest() != request["input_sha256"]
            or _read_exact(1) != b"\x01"
        ):
            raise ReadFailure("invalid_request")
        threading.Thread(target=_watch, args=(_cleanup_scratch,), daemon=True).start()
        _idle()  # An active/background repo process is busy, never killed or raced.
        result = execute(request, content)
        os.write(1, json.dumps(result, separators=(",", ":")).encode())
        _report({"status": "ok", "operation": "write"})
    except BaseException:
        _cleanup_scratch()
        _report({"status": "error", "code": "ide_write_unconfirmed"})
        os._exit(65)
    os._exit(0)
