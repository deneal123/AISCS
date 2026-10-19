"""Isolated stdlib reader executed in a sandbox, never imported from its repo.

Use ``python3 -I -c``. Root/path arrive only on stdin. Every path component is
opened relative to an owned descriptor with O_NOFOLLOW; special files cannot
block the reader. This module does not write files or inspect Git history.
"""

from __future__ import annotations

import codecs
import errno
import hashlib
import json
import os
import stat
import sys

MAX_BYTES = 256 * 1024
MAX_ENTRIES = 400
MAX_DEPTH = 6
MAX_SCANNED = 4000
HIDDEN = frozenset({".git", "node_modules", "__pycache__", ".venv", ".mypy_cache"})


class ReadFailure(Exception):
    def __init__(self, code):
        self.code = code


def components(path, *, root_allowed=False):
    if not isinstance(path, str) or len(path) > 1024:
        raise ReadFailure("ide_path_forbidden")
    if not path and root_allowed:
        return []
    parts = path.split("/")
    if (
        not path
        or "\\" in path
        or any(
            part in {"", ".", ".."}
            or part in HIDDEN
            or part.startswith(".gpthub-")
            or not part.isprintable()
            for part in parts
        )
    ):
        raise ReadFailure("ide_path_forbidden")
    return parts


def open_directory(root_fd, parts):
    current = os.dup(root_fd)
    try:
        for part in parts:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = following
        return current
    except BaseException:
        os.close(current)
        raise


def snapshot_info(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_file(root_fd, path):
    parts = components(path)
    parent = open_directory(root_fd, parts[:-1])
    try:
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ReadFailure("ide_file_unsupported")
        with os.fdopen(fd, "rb", closefd=False) as source:
            raw = source.read(MAX_BYTES + 1)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if snapshot_info(before) != snapshot_info(after):
        raise ReadFailure("ide_file_changed")
    truncated = len(raw) > MAX_BYTES
    body = raw[:MAX_BYTES]
    try:
        content = codecs.getincrementaldecoder("utf-8")().decode(body, final=not truncated)
        if b"\0" in body:
            raise UnicodeError
    except UnicodeError:
        return {
            "path": path,
            "kind": "binary",
            "size": after.st_size,
            "content": None,
            "digest": None,
            "truncated": truncated,
        }
    return {
        "path": path,
        "kind": "text",
        "size": after.st_size,
        "content": content,
        "digest": None if truncated else hashlib.sha256(body).hexdigest(),
        "truncated": truncated,
    }


def read_tree(root_fd, path):
    parts = components(path, root_allowed=True)
    base = open_directory(root_fd, parts)
    entries = []
    scanned = 0
    truncated = False

    def walk(directory, prefix, depth):
        nonlocal scanned, truncated
        pending = []
        with os.scandir(directory) as children:
            for child in children:
                scanned += 1
                if scanned > MAX_SCANNED:
                    truncated = True
                    break
                try:
                    components(child.name)
                    info = child.stat(follow_symlinks=False)
                except ReadFailure:
                    continue
                except OSError:
                    truncated = True
                    continue
                if stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode):
                    pending.append((not stat.S_ISDIR(info.st_mode), child.name, info.st_size))
        for is_file, name, size in sorted(pending):
            relative = f"{prefix}/{name}" if prefix else name
            if len(relative) > 1024:
                truncated = True
                continue
            if len(entries) >= MAX_ENTRIES:
                truncated = True
                return
            entry = {
                "path": relative,
                "type": "file" if is_file else "dir",
                "size": size if is_file else 0,
            }
            entries.append(entry)
            if not is_file:
                if depth >= MAX_DEPTH:
                    entry["incomplete"] = True
                    truncated = True
                    continue
                child_fd = None
                try:
                    child_fd = os.open(
                        name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                    )
                    walk(child_fd, relative, depth + 1)
                    if len(entries) >= MAX_ENTRIES or scanned > MAX_SCANNED:
                        entry["incomplete"] = True
                except OSError:
                    entry["incomplete"] = True
                    truncated = True
                finally:
                    if child_fd is not None:
                        os.close(child_fd)

    try:
        walk(base, path, 1)
    finally:
        os.close(base)
    return {"entries": entries, "truncated": truncated}


def execute(payload):
    root_fd = None
    try:
        operation = payload.get("operation")
        if operation not in {"tree", "file"}:
            raise ReadFailure("invalid_request")
        root_fd = os.open(payload["root"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        path = payload.get("path", "")
        return read_tree(root_fd, path) if operation == "tree" else read_file(root_fd, path)
    except ReadFailure as failure:
        return {"error": failure.code}
    except OSError as failure:
        if failure.errno == errno.ENOENT:
            return {"error": "ide_file_missing"}
        if failure.errno in {errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.EPERM}:
            return {"error": "ide_path_forbidden"}
        return {"error": "ide_read_unavailable"}
    except (TypeError, ValueError, KeyError):
        return {"error": "invalid_request"}
    finally:
        if root_fd is not None:
            os.close(root_fd)


if __name__ == "__main__":
    try:
        raw = sys.stdin.buffer.read(8193)
        request = json.loads(raw) if len(raw) <= 8192 else None
        result = execute(request) if isinstance(request, dict) else {"error": "invalid_request"}
    except (ValueError, UnicodeError):
        result = {"error": "invalid_request"}
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
