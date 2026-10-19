"""POSIX capsule capture/materialization, not an HTTP or live-editor API.

The application must hold its generation/lease and quiesce all mutators. This
kernel additionally detects metadata/namespace races; it does not freeze running
scripts. Materialization requires a fresh, empty, unpublished destination. On
failure the allocation must remain unpublished and be discarded by its owner;
this helper never deletes paths or overwrites an existing workspace to recover.
No Git command, repo import, shell, extractall, owner IDs or credentials are used.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import BinaryIO

from infrastructure.ide_bundle_format import (
    CHUNK,
    BundleFailure,
    BundleLimits,
    copy_payload,
    link_target,
    parts,
    payload_name,
    read_bundle,
    repository_path,
    write_bundle,
)


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


@dataclass(frozen=True, slots=True)
class Node:
    info: os.stat_result
    target: str | None = None


@contextmanager
def _directory(base: int, components: list[str]) -> Iterator[int]:
    current = os.dup(base)
    try:
        for part in components:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        yield current
    finally:
        os.close(current)


@contextmanager
def _root(path: str) -> Iterator[int]:
    if os.name != "posix" or not isinstance(path, str) or not path.startswith("/"):
        raise BundleFailure("ide_bundle_unsupported")
    # No intermediate trusted-root symlinks either; the sandbox supplies an
    # absolute policy path, not a user-selected host path or a resolved cwd.
    components = parts(path[1:])
    anchor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        with _directory(anchor, components) as root:
            yield root
    finally:
        os.close(anchor)


def _scan(root: int, limits: BundleLimits) -> tuple[os.stat_result, dict[str, Node]]:
    before = os.fstat(root)
    nodes: dict[str, Node] = {}
    total = 0

    def walk(directory: int, prefix: str) -> None:
        nonlocal total
        with os.scandir(directory) as children:
            for child in children:
                path = f"{prefix}/{child.name}" if prefix else child.name
                components = parts(path)
                if len(nodes) >= limits.entries or len(components) > limits.depth:
                    raise BundleFailure("ide_bundle_limit")
                info = os.stat(child.name, dir_fd=directory, follow_symlinks=False)
                if info.st_dev != before.st_dev or stat.S_IMODE(info.st_mode) & 0o7000:
                    raise BundleFailure("ide_bundle_unsupported")
                repository_path(path, "directory" if stat.S_ISDIR(info.st_mode) else "other")
                if stat.S_ISDIR(info.st_mode):
                    nodes[path] = Node(info)
                    with _directory(directory, [child.name]) as fd:
                        if _stamp(os.fstat(fd)) != _stamp(info):
                            raise BundleFailure("ide_bundle_changed")
                        walk(fd, path)
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
                    if info.st_size > limits.file_bytes or total > limits.total_bytes:
                        raise BundleFailure("ide_bundle_limit")
                    nodes[path] = Node(info)
                elif stat.S_ISLNK(info.st_mode):
                    target = os.readlink(child.name, dir_fd=directory)
                    link_target(path, target)
                    if _stamp(
                        os.stat(child.name, dir_fd=directory, follow_symlinks=False)
                    ) != _stamp(info):
                        raise BundleFailure("ide_bundle_changed")
                    nodes[path] = Node(info, target)
                else:
                    raise BundleFailure("ide_bundle_unsupported")

    walk(root, "")
    counts = Counter(
        (node.info.st_dev, node.info.st_ino)
        for node in nodes.values()
        if stat.S_ISREG(node.info.st_mode)
    )
    if any(
        node.info.st_nlink != counts[(node.info.st_dev, node.info.st_ino)]
        for node in nodes.values()
        if stat.S_ISREG(node.info.st_mode)
    ):
        raise BundleFailure("ide_bundle_unsupported")
    return before, nodes


@contextmanager
def _payload(root: int, path: str, node: Node) -> Iterator[BinaryIO]:
    components = parts(path)
    with _directory(root, components[:-1]) as parent:
        fd = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        if _stamp(os.fstat(fd)) != _stamp(node.info) or not stat.S_ISREG(os.fstat(fd).st_mode):
            raise BundleFailure("ide_bundle_changed")
        with os.fdopen(fd, "rb", closefd=False) as source:
            yield source
        if _stamp(os.fstat(fd)) != _stamp(node.info):
            raise BundleFailure("ide_bundle_changed")
    finally:
        os.close(fd)


def _digest(root: int, path: str, node: Node) -> str:
    digest, size = hashlib.sha256(), 0
    with _payload(root, path, node) as source:
        while chunk := source.read(min(CHUNK, node.info.st_size - size + 1)):
            size += len(chunk)
            if size > node.info.st_size:
                raise BundleFailure("ide_bundle_changed")
            digest.update(chunk)
    if size != node.info.st_size:
        raise BundleFailure("ide_bundle_changed")
    return digest.hexdigest()


def _manifest(root: int, nodes: dict[str, Node]) -> list[dict]:
    entries, inodes = [], {}
    for path, node in sorted(nodes.items()):
        info = node.info
        entry = dict(
            path=path, kind="directory", mode=stat.S_IMODE(info.st_mode), mtime_ns=info.st_mtime_ns
        )
        if stat.S_ISLNK(info.st_mode):
            entry.update(kind="symlink", target=node.target)
        elif stat.S_ISREG(info.st_mode):
            inode = (info.st_dev, info.st_ino)
            if inode in inodes:
                entry.update(kind="hardlink", target=inodes[inode])
            else:
                inodes[inode] = path
                entry.update(kind="file", size=info.st_size, sha256=_digest(root, path, node))
        entries.append(entry)
    return entries


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except BundleFailure:
        raise
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, OverflowError):
        raise BundleFailure("ide_bundle_unavailable") from None


def capture_bundle(root_path: str, target: BinaryIO, limits: BundleLimits) -> int:
    """Write a complete verified capsule; caller discards output on any failure."""
    with _errors(), _root(root_path) as root:
        before, nodes = _scan(root, limits)
        entries = _manifest(root, nodes)
        size = write_bundle(
            entries,
            lambda entry: _payload(root, entry["path"], nodes[entry["path"]]),
            target,
            limits,
        )
        after, current = _scan(root, limits)
        if (
            _stamp(before) != _stamp(after)
            or nodes.keys() != current.keys()
            or any(
                _stamp(node.info) != _stamp(current[path].info)
                or node.target != current[path].target
                for path, node in nodes.items()
            )
        ):
            raise BundleFailure("ide_bundle_changed")
        return size


def _metadata(fd: int, entry: dict) -> None:
    os.fchmod(fd, entry["mode"])
    os.utime(fd, ns=(entry["mtime_ns"], entry["mtime_ns"]))
    actual = os.fstat(fd)
    if stat.S_IMODE(actual.st_mode) != entry["mode"] or actual.st_mtime_ns != entry["mtime_ns"]:
        raise BundleFailure("ide_bundle_unsupported")
    os.fsync(fd)


def _restore_entry(root: int, archive, index: int, entry: dict) -> None:
    components = parts(entry["path"])
    with _directory(root, components[:-1]) as parent:
        name, kind = components[-1], entry["kind"]
        if kind == "directory":
            os.mkdir(name, 0o700, dir_fd=parent)
        elif kind == "symlink":
            os.symlink(entry["target"], name, dir_fd=parent)
            os.utime(
                name,
                ns=(entry["mtime_ns"], entry["mtime_ns"]),
                dir_fd=parent,
                follow_symlinks=False,
            )
            if os.stat(name, dir_fd=parent, follow_symlinks=False).st_mtime_ns != entry["mtime_ns"]:
                raise BundleFailure("ide_bundle_unsupported")
        elif kind == "hardlink":
            target = parts(entry["target"])
            with _directory(root, target[:-1]) as original:
                os.link(
                    target[-1], name, src_dir_fd=original, dst_dir_fd=parent, follow_symlinks=False
                )
        else:
            fd = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
            )
            with os.fdopen(fd, "wb") as destination, archive.open(payload_name(index)) as source:
                copy_payload(source, destination, entry)
                destination.flush()
                _metadata(destination.fileno(), entry)


def restore_empty(root_path: str, source: BinaryIO, limits: BundleLimits) -> int:
    """Materialize only a fresh unpublished root; never use this on a live repo.

    Full archive verification precedes the first filesystem write. I/O failure
    may leave partial files in that unpublished allocation, never a success ack.
    A trusted lifecycle owner must discard it instead of retrying over contents.
    """
    with _errors(), read_bundle(source, limits) as (entries, archive), _root(root_path) as root:
        with os.scandir(root) as children:
            if next(children, None) is not None:
                raise BundleFailure("ide_bundle_target_not_empty")
        for index, entry in enumerate(entries):
            _restore_entry(root, archive, index, entry)
        # Children before parents: restrictive final directory modes must not
        # prevent restoring their contents. No ancestor is ever a symlink.
        for entry in reversed(entries):
            if entry["kind"] == "directory":
                with _directory(root, parts(entry["path"])) as directory:
                    _metadata(directory, entry)
        os.fsync(root)
        return len(entries)
