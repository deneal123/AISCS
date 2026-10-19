"""Atomic, no-clobber Linux rename between anchored repository directories."""

import ctypes
import errno
import json
import os
import stat
import threading
import time

from infrastructure.ide_bundle_runtime import _idle, _read_exact, _report, _watch
from infrastructure.ide_read_runtime import (
    ReadFailure,
    components,
    open_directory,
    read_file,
    snapshot_info,
)


def move(request):
    root = os.open(request["root"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    source_parent, destination_parent = None, None
    try:
        source, destination = components(request["path"]), components(request["destination"])
        if source == destination:
            raise ReadFailure("ide_file_changed")
        if destination[: len(source)] == source:
            raise ReadFailure("ide_path_forbidden")
        source_parent = open_directory(root, source[:-1])
        destination_parent = open_directory(root, destination[:-1])
        before = os.stat(source[-1], dir_fd=source_parent, follow_symlinks=False)
        if (
            not (stat.S_ISREG(before.st_mode) or stat.S_ISDIR(before.st_mode))
            or (stat.S_ISREG(before.st_mode) and before.st_nlink != 1)
            or before.st_uid != os.geteuid()
        ):
            raise ReadFailure("ide_file_unsupported")
        if not (before.st_dev == os.fstat(destination_parent).st_dev == os.fstat(root).st_dev):
            raise ReadFailure("ide_path_forbidden")
        digest = request["expected_digest"]
        if digest is not None:
            if stat.S_ISDIR(before.st_mode):
                raise ReadFailure("ide_file_unsupported")
            actual = read_file(root, request["path"])
            if actual["digest"] != digest:
                raise ReadFailure("ide_file_changed")
        # Recheck both anchored ancestors and the source before the atomic rename.
        for parts, descriptor in ((source, source_parent), (destination, destination_parent)):
            check = open_directory(root, parts[:-1])
            try:
                if snapshot_info(os.fstat(check))[:2] != snapshot_info(os.fstat(descriptor))[:2]:
                    raise ReadFailure("ide_file_changed")
            finally:
                os.close(check)
        if snapshot_info(before) != snapshot_info(
            os.stat(source[-1], dir_fd=source_parent, follow_symlinks=False)
        ):
            raise ReadFailure("ide_file_changed")
        if time.time() >= request["deadline"]:
            raise ReadFailure("ide_runtime_expired")
        library = ctypes.CDLL(None, use_errno=True)
        rename = library.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        if rename(
            source_parent,
            os.fsencode(source[-1]),
            destination_parent,
            os.fsencode(destination[-1]),
            1,
        ):
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        os.fsync(source_parent)
        os.fsync(destination_parent)
        return dict(
            moved=True,
            path=request["destination"],
            moved_from=request["path"],
            size=0 if stat.S_ISDIR(before.st_mode) else before.st_size,
        )
    finally:
        for descriptor in (source_parent, destination_parent, root):
            if descriptor is not None:
                os.close(descriptor)


def execute(request):
    try:
        return move(request)
    except ReadFailure as error:
        return {"error": error.code}
    except OSError as error:
        code = {
            errno.EEXIST: "ide_file_changed",
            errno.ENOENT: "ide_file_missing",
            errno.ELOOP: "ide_path_forbidden",
            errno.ENOTDIR: "ide_path_forbidden",
            errno.EINVAL: "ide_path_forbidden",
            errno.ENOTEMPTY: "ide_file_changed",
        }.get(error.errno, "ide_write_unconfirmed")
        return {"error": code}


def main():
    try:
        header = bytearray()
        while len(header) <= 8192:
            char = _read_exact(1)
            if char == b"\n":
                break
            header.extend(char)
        else:
            raise ValueError
        request = json.loads(header)
        if _read_exact(1) != b"\x01":
            raise ValueError
        threading.Thread(target=_watch, daemon=True).start()
        _idle()
        result = execute(request)
    except BaseException:
        result = {"error": "ide_write_unconfirmed"}
    os.write(1, json.dumps(result, separators=(",", ":")).encode())
    _report({"status": "ok", "operation": "move"})
    os._exit(0)
