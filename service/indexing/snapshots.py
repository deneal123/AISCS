"""Portable index snapshots: everything a fresh server needs to rebuild without providers.

A snapshot holds the build inputs that Git does not carry (raw originals, normalized
documents, the content-addressed embedding cache) plus the generation it reproduces.
Backend state (Neo4j, Qdrant, ``indexed.json`` checkpoints) and secrets are never
included: on restore the normal ``build`` re-imports both stores from the cache with
zero provider calls and must reproduce the recorded generation before ``publish``.
"""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ..common.errors import DataError
from ..common.hashing import sha256_file
from ..common.jsonio import atomic_write_json

FORMAT = "aspa-index-snapshot"
VERSION = 1
SAFE_MEMBER = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
FORBIDDEN = frozenset({"runtime.env", "active.json", "writer.lock", "indexed.json"})
CACHE = "embeddings.sqlite3"




def _member(name: str) -> str:
    pure = PurePosixPath(name)
    if (
        not SAFE_MEMBER.fullmatch(name)
        or pure.is_absolute()
        or ".." in pure.parts
        or pure.name in FORBIDDEN
    ):
        raise DataError("unsafe or forbidden snapshot member: " + name)
    return name


def export_snapshot(
    state: Path, members: list[str], archive: Path, *, index: str, identity: dict[str, Any]
) -> dict[str, Any]:
    """Write ``archive`` with the listed state files and a SHA-256 manifest."""
    state = state.resolve()
    archive.parent.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="aspa-snapshot-") as tmp:
        sources: dict[str, Path] = {}
        for name in sorted(set(members)):
            source = state / _member(name)
            if not source.is_file():
                raise DataError("snapshot input is missing: " + name)
            if name == CACHE:
                # Online backup gives a consistent copy even while readers hold the file.
                copy = Path(tmp) / CACHE
                live, target = sqlite3.connect(source), sqlite3.connect(copy)
                try:
                    live.backup(target)
                finally:  # ``with`` only commits; Windows keeps unclosed files locked
                    target.close()
                    live.close()
                source = copy
            sources[name] = source
            files[name] = {"sha256": sha256_file(source), "bytes": source.stat().st_size}
        manifest = {
            "format": FORMAT,
            "version": VERSION,
            "index": index,
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            **identity,
            "files": files,
        }
        partial = archive.with_name(archive.name + ".partial")
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("snapshot.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for name, source in sources.items():
                bundle.write(source, name)
        partial.replace(archive)
    return {
        **{k: v for k, v in manifest.items() if k != "files"},
        "archive": archive.name,
        "archive_sha256": sha256_file(archive),
        "archive_bytes": archive.stat().st_size,
        "file_count": len(files),
        "payload_bytes": sum(f["bytes"] for f in files.values()),
    }


def read_manifest(archive: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read("snapshot.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise DataError("not a readable index snapshot") from exc
    if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
        raise DataError("unsupported snapshot format")
    return manifest


def restore_snapshot(
    archive: Path, state: Path, *, index: str, force: bool = False
) -> dict[str, Any]:
    """Verify every member against the manifest, then place files into ``state``.

    Refuses a populated state directory unless ``force``; never writes the active
    pointer, so nothing is served until the rebuilt generation is published."""
    manifest = read_manifest(archive)
    if manifest.get("index") != index:
        raise DataError(f"snapshot is for the {manifest.get('index')} index, not {index}")
    state = state.resolve()
    state.mkdir(parents=True, exist_ok=True)
    occupied = [n for n in manifest["files"] if (state / n).exists()]
    if occupied and not force:
        raise DataError(
            "state directory already holds snapshot files; use --force to overwrite them"
        )
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist()) - {"snapshot.json"}
        if names != set(manifest["files"]):
            raise DataError("snapshot members differ from its manifest")
        with tempfile.TemporaryDirectory(prefix=".restore-", dir=state) as tmp:
            staged = Path(tmp)
            for name in sorted(names):
                target = staged / _member(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(name) as source, target.open("wb") as sink:
                    for block in iter(lambda: source.read(1 << 20), b""):
                        sink.write(block)
                if sha256_file(target) != manifest["files"][name]["sha256"]:
                    raise DataError("snapshot member digest mismatch: " + name)
            for name in sorted(names):  # all members verified: move them into place
                destination = state / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                (staged / name).replace(destination)
    return {
        "ok": True,
        "index": index,
        "restored_files": len(names),
        "overwritten": len(occupied),
        "expected_generation": manifest.get("generation"),
        "next": "run build, compare the generation with expected_generation, then publish",
    }


def write_record(path: Path, record: dict[str, Any]) -> None:
    """Tracked verification anchor: archive digest and the generation it rebuilds."""
    atomic_write_json(path, record)


def check_record(path: Path, archive: Path) -> str | None:
    """Warn when the archive is not the one recorded in the cloned repository."""
    if not path.is_file():
        return "no tracked snapshot record in this checkout"
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("archive_sha256") != sha256_file(archive):
        return "archive differs from the tracked snapshot record"
    return None
