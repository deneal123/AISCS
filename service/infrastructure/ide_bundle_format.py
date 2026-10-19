"""Private bounded repository capsule: canonical manifest + stored ZIP payloads.

ZIP names are generated indices, never repository paths. No extract/extractall,
compression, ZIP64, encrypted members, extras, comments or implicit truncation.
This is a checkpoint format, not the public repository download interface.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import struct
import zipfile
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import BinaryIO

CHUNK = 65536
EOCD = struct.Struct("<4s4H2LH")
LOCAL = struct.Struct("<4s5H3L2H")
ERRORS = frozenset(
    {
        "ide_bundle_invalid",
        "ide_bundle_limit",
        "ide_bundle_changed",
        "ide_bundle_unsupported",
        "ide_bundle_busy",
        "ide_bundle_target_not_empty",
        "ide_bundle_unavailable",
    }
)
UNSUPPORTED_GIT = frozenset(
    {
        ".git/commondir",
        ".git/worktrees",
        ".git/objects/info/alternates",
        ".git/objects/info/http-alternates",
    }
)


class BundleFailure(Exception):
    def __init__(self, code: str = "ide_bundle_invalid") -> None:
        self.code = code if isinstance(code, str) and code in ERRORS else "ide_bundle_invalid"
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class BundleLimits:
    entries: int
    file_bytes: int
    total_bytes: int
    archive_bytes: int
    manifest_bytes: int
    depth: int

    def __post_init__(self) -> None:
        values = (
            self.entries,
            self.file_bytes,
            self.total_bytes,
            self.archive_bytes,
            self.manifest_bytes,
            self.depth,
        )
        if any(type(value) is not int or value < 1 for value in values):
            raise BundleFailure()
        # ZIP64 is deliberately outside this format; these are technical caps,
        # not a replacement for the application owner's resource/user quotas.
        if (
            self.entries > 65533
            or self.archive_bytes >= 2**31
            or self.depth > 64
            or self.manifest_bytes > min(self.archive_bytes, 16 * 1024 * 1024)
        ):
            raise BundleFailure()


def parts(path: str) -> list[str]:
    if (
        not isinstance(path, str)
        or not path
        or not path.isprintable()
        or len(path.encode("utf-8")) > 1024
        or "\\" in path
    ):
        raise BundleFailure()
    result = path.split("/")
    if any(value in {"", ".", ".."} for value in result):
        raise BundleFailure()
    return result


def link_target(path: str, target: str) -> str:
    if (
        not isinstance(target, str)
        or not target
        or not target.isprintable()
        or len(target.encode("utf-8")) > 1024
        or "\\" in target
        or target.startswith("/")
    ):
        raise BundleFailure("ide_bundle_unsupported")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
    if resolved == ".." or resolved.startswith("../"):
        raise BundleFailure("ide_bundle_unsupported")
    return resolved


def repository_path(path: str, kind: str) -> None:
    if path in UNSUPPORTED_GIT or (path == ".git" and kind != "directory"):
        raise BundleFailure("ide_bundle_unsupported")
    if path.startswith(".git/") and path.endswith(".lock"):
        raise BundleFailure("ide_bundle_busy")


def _validate_links(entries: list[dict]) -> None:
    """Resolve virtual symlink chains, including '..' after a symlink to '.'."""
    links = {entry["path"]: entry["target"] for entry in entries if entry["kind"] == "symlink"}
    steps = 64 * max(1, len(entries))
    for path, target in links.items():
        remaining = deque((posixpath.dirname(path) + "/" + target).split("/"))
        resolved: list[str] = []
        followed = 0
        while remaining:
            steps -= 1
            if steps < 0:
                raise BundleFailure("ide_bundle_limit")
            part = remaining.popleft()
            if part in {"", "."}:
                continue
            if part == "..":
                if not resolved:
                    raise BundleFailure("ide_bundle_unsupported")
                resolved.pop()
                continue
            candidate = "/".join([*resolved, part])
            if candidate in links:
                followed += 1
                if followed > 40:
                    raise BundleFailure("ide_bundle_unsupported")
                remaining.extendleft(reversed(links[candidate].split("/")))
            else:
                resolved.append(part)
                if len(resolved) > 64:
                    raise BundleFailure("ide_bundle_limit")


def validate_entries(entries: list[dict], limits: BundleLimits) -> list[dict]:
    if type(entries) is not list or len(entries) > limits.entries:
        raise BundleFailure("ide_bundle_limit")
    seen, total, previous = {}, 0, ""
    for entry in entries:
        if type(entry) is not dict:
            raise BundleFailure()
        path, kind = entry.get("path"), entry.get("kind")
        components = parts(path)
        if type(kind) is not str:
            raise BundleFailure()
        repository_path(path, kind)
        if len(components) > limits.depth:
            raise BundleFailure("ide_bundle_limit")
        if path <= previous or any(
            seen.get("/".join(components[:index]), {}).get("kind") != "directory"
            for index in range(1, len(components))
        ):
            raise BundleFailure()
        expected = {"path", "kind", "mode", "mtime_ns"}
        if kind == "file":
            expected |= {"size", "sha256"}
            if (
                type(entry.get("size")) is not int
                or not 0 <= entry["size"] <= limits.file_bytes
                or not isinstance(entry.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            ):
                raise BundleFailure("ide_bundle_limit")
            total += entry["size"]
        elif kind in {"symlink", "hardlink"}:
            expected.add("target")
            if kind == "symlink":
                link_target(path, entry.get("target"))
                if entry.get("mode") != 0o777:
                    raise BundleFailure("ide_bundle_unsupported")
            else:
                if not isinstance(entry.get("target"), str):
                    raise BundleFailure()
                target = seen.get(entry["target"])
                if (
                    target is None
                    or target["kind"] != "file"
                    or any(entry.get(key) != target.get(key) for key in ("mode", "mtime_ns"))
                ):
                    raise BundleFailure()
                total += target["size"]
        elif kind != "directory":
            raise BundleFailure("ide_bundle_unsupported")
        if (
            set(entry) != expected
            or type(entry.get("mode")) is not int
            or not 0 <= entry["mode"] <= 0o777
            or type(entry.get("mtime_ns")) is not int
            or not -(2**63) <= entry["mtime_ns"] < 2**63
        ):
            raise BundleFailure()
        if total > limits.total_bytes:
            raise BundleFailure("ide_bundle_limit")
        seen[path], previous = entry, path
    _validate_links(entries)
    return entries


def payload_name(index: int) -> str:
    return f"data/{index:08x}"


class BoundedOutput:
    """Seekable writer required by ZipFile; the caller discards it on failure."""

    def __init__(self, target: BinaryIO, maximum: int) -> None:
        self.target, self.maximum = target, maximum

    def write(self, data: bytes) -> int:
        if self.target.tell() + len(data) > self.maximum:
            raise BundleFailure("ide_bundle_limit")
        written = self.target.write(data)
        if written != len(data):
            raise BundleFailure("ide_bundle_unavailable")
        return written

    def __getattr__(self, name: str):
        return getattr(self.target, name)


def _member(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.create_system, info.external_attr = 3, (0o100600 << 16)
    return info


def copy_payload(source: BinaryIO, target: BinaryIO | None, entry: dict) -> None:
    digest, count = hashlib.sha256(), 0
    while chunk := source.read(min(CHUNK, entry["size"] - count + 1)):
        if not isinstance(chunk, bytes) or len(chunk) > min(CHUNK, entry["size"] - count + 1):
            raise BundleFailure()
        count += len(chunk)
        if count > entry["size"]:
            raise BundleFailure("ide_bundle_changed")
        if target is not None and target.write(chunk) != len(chunk):
            raise BundleFailure("ide_bundle_unavailable")
        digest.update(chunk)
    if count != entry["size"] or digest.hexdigest() != entry["sha256"]:
        raise BundleFailure("ide_bundle_changed")


def write_bundle(
    entries: list[dict],
    open_payload: Callable[[dict], AbstractContextManager[BinaryIO]],
    target: BinaryIO,
    limits: BundleLimits,
) -> int:
    validate_entries(entries, limits)
    manifest = json.dumps(
        {"format": "gpthub-repository", "version": 1, "entries": entries},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    if len(manifest) > limits.manifest_bytes:
        raise BundleFailure("ide_bundle_limit")
    if target.tell() != 0:
        raise BundleFailure()
    if target.seek(0, 2) != 0:
        raise BundleFailure()
    with zipfile.ZipFile(
        BoundedOutput(target, limits.archive_bytes),
        "w",
        allowZip64=False,
        compression=zipfile.ZIP_STORED,
    ) as archive:
        archive.writestr(_member("manifest.json"), manifest)
        for index, entry in enumerate(entries):
            if entry["kind"] == "file":
                with (
                    open_payload(entry) as source,
                    archive.open(_member(payload_name(index)), "w") as dest,
                ):
                    copy_payload(source, dest, entry)
    target.flush()
    return target.tell()


def _unique(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BundleFailure()
        result[key] = value
    return result


def _preflight(source: BinaryIO, limits: BundleLimits) -> None:
    source.seek(0, 2)
    length = source.tell()
    if not EOCD.size <= length <= limits.archive_bytes:
        raise BundleFailure("ide_bundle_limit")
    source.seek(-EOCD.size, 2)
    signature, disk, start, count_disk, count, size, offset, comment = EOCD.unpack(
        source.read(EOCD.size)
    )
    if (
        signature != b"PK\x05\x06"
        or disk
        or start
        or comment
        or count != count_disk
        or not 1 <= count <= limits.entries + 1
        or count >= 65535
        or offset + size != length - EOCD.size
        or size > count * 128
    ):
        raise BundleFailure()
    source.seek(0)


def _local_record(source: BinaryIO, info: zipfile.ZipInfo, offset: int) -> int:
    source.seek(offset)
    signature, version, flags, method, clock, date, crc, packed, size, name, extra = LOCAL.unpack(
        source.read(LOCAL.size)
    )
    encoded = info.filename.encode("ascii")
    if (
        signature != b"PK\x03\x04"
        or version != 20
        or flags
        or method
        or clock
        or date != 33
        or crc != info.CRC
        or packed != info.compress_size
        or size != info.file_size
        or name != len(encoded)
        or extra
        or source.read(name) != encoded
    ):
        raise BundleFailure()
    return offset + LOCAL.size + name + size


@contextmanager
def read_bundle(
    source: BinaryIO, limits: BundleLimits
) -> Iterator[tuple[list[dict], zipfile.ZipFile]]:
    """Validate complete envelope and all payloads before yielding any restore input."""
    validated = False
    try:
        _preflight(source, limits)
        archive = zipfile.ZipFile(source, "r", allowZip64=False)
        with archive:
            infos = archive.infolist()
            if len(infos) > limits.entries + 1 or not infos or infos[0].filename != "manifest.json":
                raise BundleFailure()
            offset = 0
            for info in infos:
                if (
                    info.filename != info.orig_filename
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.file_size != info.compress_size
                    or info.extra
                    or info.comment
                    or info.flag_bits
                    or info.header_offset != offset
                    or info.is_dir()
                    or info.create_system != 3
                    or info.create_version != 20
                    or info.extract_version != 20
                    or info.volume
                    or info.internal_attr
                    or info.external_attr != (0o100600 << 16)
                    or info.date_time != (1980, 1, 1, 0, 0, 0)
                ):
                    raise BundleFailure()
                # All canonical member names are short ASCII; reject gaps and
                # overlapping local records, not just the central-directory view.
                offset = _local_record(source, info, offset)
            if offset != archive.start_dir or infos[0].file_size > limits.manifest_bytes:
                raise BundleFailure("ide_bundle_limit")
            manifest = json.loads(archive.read(infos[0]), object_pairs_hook=_unique)
            if (
                type(manifest) is not dict
                or set(manifest) != {"format", "version", "entries"}
                or manifest["format"] != "gpthub-repository"
                or type(manifest["version"]) is not int
                or manifest["version"] != 1
            ):
                raise BundleFailure()
            entries = validate_entries(manifest["entries"], limits)
            expected = ["manifest.json"] + [
                payload_name(index)
                for index, entry in enumerate(entries)
                if entry["kind"] == "file"
            ]
            if [info.filename for info in infos] != expected:
                raise BundleFailure()
            for index, entry in enumerate(entries):
                if entry["kind"] == "file":
                    info = archive.getinfo(payload_name(index))
                    if info.file_size != entry["size"]:
                        raise BundleFailure()
                    with archive.open(info) as payload:
                        copy_payload(payload, None, entry)
            validated = True
            yield entries, archive
    except BundleFailure:
        raise
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        RecursionError,
        struct.error,
        zipfile.BadZipFile,
        NotImplementedError,
    ):
        if validated:
            # A consumer's output error is not evidence of corrupt input.
            raise
        raise BundleFailure() from None
