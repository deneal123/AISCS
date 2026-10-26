"""Registry snapshots before writes and retention of automatic snapshots."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from ..common.clock import utc_now
from ..common.errors import DataError
from ..common.hashing import sha256
from ..common.jsonio import atomic_write_json
from ..registry.layout import data_path

CANONICAL_FILES = (
    "records.json",
    "clusters.json",
    "ST.json",
    "aliases.json",
    "vocabularies.json",
    "source-record.schema.json",
    "audit-report.json",
    "validation-log.json",
    "evidence-matrix.json",
    "evidence-review-ledger.json",
    "scientific-contract.json",
    "human-dataset-matrix.json",
    "completeness-report.json",
    "search-protocol.json",
    "novelty-landscape.json",
    "dissertation-concept.json",
    "runtime-audit.json",
    "ecap-scs-audit.json",
    "drosophila-connectome-audit.json",
    "drosophila-nociception-audit.json",
    "synthetic-domain-audit.json",
    "ns06-prior-art-audit.json",
    "scs-outcome-audit.json",
    "ns11-prediction-audit.json",
    "human-ecap-scs-access-audit.json",
)

ARCHIVE_RETENTION = 2


def _prune_snapshot_directory(snapshot_root: Path, keep_latest: int) -> list[Path]:
    if keep_latest < 1:
        raise ValueError("keep_latest must be positive")
    if not snapshot_root.is_dir():
        return []
    dated = sorted(
        [
            path
            for path in snapshot_root.iterdir()
            if path.is_dir()
            and not path.is_symlink()
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{6}Z(?:-.+)?", path.name)
            and (path / "manifest.json").is_file()
            and not (path / ".keep").exists()
        ],
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    removed: list[Path] = []
    for path in dated[:-keep_latest]:
        if path.resolve().parent != snapshot_root:
            raise DataError(f"unsafe snapshot path: {path}")
        shutil.rmtree(path)
        removed.append(path)
    return removed


def prune_archive_snapshots(root: Path | str, keep_latest: int = ARCHIVE_RETENTION) -> list[Path]:
    """Retain recent explicit snapshots and any pinned historical baseline."""
    root = Path(root).resolve()
    archive_root = (root / "archive").resolve()
    if not archive_root.is_relative_to(root):
        raise DataError(f"unsafe archive path: {archive_root}")
    return _prune_snapshot_directory(archive_root, keep_latest)


def snapshot_repository(
    root: Path | str, label: str | None = None, *, persistent: bool = False
) -> Path:
    root = Path(root).resolve()
    timestamp = utc_now().strftime("%Y-%m-%dT%H%M%SZ")
    safe_label = "".join(char for char in (label or "") if char.isalnum() or char in "-_")
    directory_name = timestamp + (f"-{safe_label}" if safe_label else "")
    snapshot_root = root / "archive" if persistent else root.parent / ".work" / "research-snapshots"
    resolved_snapshot_root = snapshot_root.resolve()
    allowed_root = root if persistent else root.parent
    if not resolved_snapshot_root.is_relative_to(allowed_root):
        raise DataError(f"unsafe snapshot directory: {snapshot_root}")
    destination = resolved_snapshot_root / directory_name
    if destination.exists():
        raise DataError(f"snapshot already exists: {destination}")
    destination.mkdir(parents=True)
    entries: list[dict[str, Any]] = []
    for name in CANONICAL_FILES:
        source = data_path(root, name)
        if not source.is_file():
            continue
        target = data_path(destination, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        entries.append(
            {
                "name": target.relative_to(destination).as_posix(),
                "bytes": target.stat().st_size,
                "sha256": sha256(target),
            }
        )
    todo_source = root.parent / "TODO.md"
    if todo_source.is_file():
        todo_target = destination / "TODO.md"
        shutil.copy2(todo_source, todo_target)
        entries.append(
            {
                "name": "TODO.md",
                "source": "../TODO.md",
                "bytes": todo_target.stat().st_size,
                "sha256": sha256(todo_target),
            }
        )
    manifest = {
        "snapshot_at": utc_now().isoformat(timespec="seconds"),
        "status": "immutable_pre_publish_snapshot",
        "label": label,
        "files": entries,
        "mutation_policy": "Do not edit; publish changes only to the working research JSON files.",
    }
    atomic_write_json(destination / "manifest.json", manifest)
    if persistent:
        prune_archive_snapshots(root)
    else:
        _prune_snapshot_directory(resolved_snapshot_root, ARCHIVE_RETENTION)
    return destination
