"""Standalone stdlib extractor executed inside the Linux workspace runtime.

All writes are relative to pinned directory descriptors. No checked pathname
is resolved a second time for temporary-file creation or publication.
"""

import os
import sys
import zipfile
from contextlib import contextmanager
from uuid import uuid4


def relative_parts(root, path):
    root, path = os.path.abspath(root), os.path.abspath(path)
    if os.path.commonpath([root, path]) != root:
        raise ValueError("outside_root")
    parts = os.path.relpath(path, root).split(os.sep)
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("invalid_path")
    return parts


@contextmanager
def directory(anchor, parts, *, create=False):
    fd = os.dup(anchor)
    try:
        for part in parts:
            if part in ("", ".", "..") or os.sep in part:
                raise ValueError("invalid_path")
            if create:
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def member_parts(name):
    # ZIP member paths use '/', regardless of the machine which created them.
    if name.startswith("/") or "\\" in name or "\x00" in name:
        return None
    parts = name.split("/")
    return None if any(part in ("", ".", "..") for part in parts) else parts


def exists(parent, name):
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def publish_member(archive, info, parent, name, remaining):
    temporary = ".unpack-" + uuid4().hex
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
    )
    written = 0
    try:
        with os.fdopen(fd, "wb") as output, archive.open(info) as source:
            while chunk := source.read(min(65536, remaining - written + 1)):
                if len(chunk) > remaining - written:
                    return None
                output.write(chunk)
                written += len(chunk)
        try:
            os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        except FileExistsError:
            return False, 0
        return True, written
    finally:
        os.unlink(temporary, dir_fd=parent)


def extract(archive, destination, max_files, max_bytes):
    total = taken = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        parts = member_parts(info.filename)
        if parts is None:
            continue
        try:
            with directory(destination, parts[:-1], create=True) as parent:
                if exists(parent, parts[-1]):
                    continue
                if taken >= max_files or info.file_size > max_bytes - total:
                    return "__TRUNCATED__", taken
                result = publish_member(archive, info, parent, parts[-1], max_bytes - total)
                if result is None:
                    return "__TRUNCATED__", taken
                published, written = result
                total += written
                taken += int(published)
        except (NotADirectoryError, FileExistsError):
            # A member parent is a file/symlink, not an admitted directory.
            continue
    return "__OK__", taken


def main(source, destination, root, max_files, max_bytes):
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        print("__REFUSED__")
        return
    anchor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        source_parts = relative_parts(root, source)
        with directory(anchor, source_parts[:-1]) as parent:
            fd = os.open(source_parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, "rb") as source_file:
            if not zipfile.is_zipfile(source_file):
                print("__NOT_ARCHIVE__")
                return
            with zipfile.ZipFile(source_file) as archive:
                with directory(anchor, relative_parts(root, destination), create=True) as target:
                    print(*extract(archive, target, max_files, max_bytes))
    finally:
        os.close(anchor)


if __name__ == "__main__":
    try:
        main(*sys.argv[1:4], int(sys.argv[4]), int(sys.argv[5]))
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        # Compiler/runtime errors never expose member names, paths or bodies.
        print("__REFUSED__")
