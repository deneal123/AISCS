"""Corpus candidates and conservative discovery of local source files."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...common.errors import CorpusError
from ...indexing.fetch import DEFAULT_MAX_BYTES
from .text import as_list

DISCOVERY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".xml",
        ".nxml",
        ".html",
        ".htm",
        ".txt",
        ".md",
        ".rst",
        ".json",
        ".jsonl",
        ".csv",
        ".tsv",
        ".bib",
        ".ris",
        ".yaml",
        ".yml",
    }
)

EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".knowledge",
        "build",
        "dist",
    }
)

# Structural registry artifacts are never source candidates.
STRUCTURAL_BASENAMES: frozenset[str] = frozenset(
    {
        "records.json",
        "aliases.json",
        "clusters.json",
        "ST.json",
        "release-manifest.json",
        "source-record.schema.json",
        "vocabularies.json",
        "applied-batches.json",
        "manifest.json",
        "package-lock.json",
        "uv.lock",
        "pyproject.toml",
    }
)


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------


def _new_candidate(
    *,
    source_id: str | None,
    provisional_id: str,
    paths: Sequence[str],
    primary_urls: Sequence[str],
    identity_verified_claim: bool,
    expected: Mapping[str, Any] | None = None,
    source_class: str = "candidate",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "provisional_id": provisional_id,
        "paths": list(dict.fromkeys(paths)),
        "primary_urls": list(dict.fromkeys(primary_urls)),
        "identity_verified_claim": bool(identity_verified_claim),
        "expected": dict(expected) if expected else None,
        "source_class": source_class,
    }


def normalize_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate and group explicit ``{source_id,path,primary_url,identity_verified}``.

    Multiple candidates for one ``source_id`` are merged; ``identity_verified`` is
    only an input claim and is re-checked later against document content.
    """
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise CorpusError("candidates must be a sequence of mappings")
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in candidates:
        if not isinstance(raw, Mapping):
            raise CorpusError("every candidate must be a mapping")
        source_id = raw.get("source_id")
        if source_id is not None:
            source_id = str(source_id)
            if not re.fullmatch(r"S[0-9]{3,}", source_id):
                raise CorpusError(f"invalid source_id: {source_id!r}")
        paths = as_list(raw.get("path")) + as_list(raw.get("paths"))
        urls = as_list(raw.get("primary_url")) + as_list(raw.get("primary_urls"))
        if not paths and not urls:
            raise CorpusError(f"candidate {source_id or '<discovery>'} has no path or primary_url")
        expected = raw.get("expected")
        if expected is not None and not isinstance(expected, Mapping):
            raise CorpusError("candidate 'expected' must be a mapping when present")
        key = source_id if source_id is not None else f"local:{paths[0]}"
        if key not in grouped:
            order.append(key)
            grouped[key] = _new_candidate(
                source_id=source_id,
                provisional_id=key,
                paths=paths,
                primary_urls=urls,
                identity_verified_claim=bool(raw.get("identity_verified", False)),
                expected=expected,
            )
        else:
            merged = grouped[key]
            merged["paths"] = list(dict.fromkeys([*merged["paths"], *paths]))
            merged["primary_urls"] = list(dict.fromkeys([*merged["primary_urls"], *urls]))
            merged["identity_verified_claim"] = merged["identity_verified_claim"] or bool(
                raw.get("identity_verified", False)
            )
            if expected and not merged["expected"]:
                merged["expected"] = dict(expected)
    return [grouped[key] for key in order]


DEFAULT_MAX_SCRATCH_FILES = 5000


def _classify_relative(parts: Sequence[str]) -> str:
    if parts and parts[0] == ".work":
        return "scratch"
    if parts and parts[0] in {
        "data",
        "tests",
        "docs",
        "migrations",
        "scripts",
        "service",
        "knowledge",
        "publications",
        "presentation",
        "text",
        "agents",
        "backend",
        "frontend",
        "infra",
        "docker",
    }:
        return "repository_artifact"
    return "candidate"


def scan_local_sources(
    root: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_scratch_files: int = DEFAULT_MAX_SCRATCH_FILES,
) -> tuple[list[dict[str, Any]], bool]:
    """Classify local files without ever parsing or indexing them.

    ``.work`` is walked last so scratch volume can never hide registry artifacts
    or root-level candidates. Scratch entries beyond ``max_scratch_files`` are
    dropped and the truncation is reported explicitly.
    """
    root = root.resolve()
    found: list[dict[str, Any]] = []
    truncated = False
    scratch_count = 0

    def collect(path: Path, *, is_scratch: bool) -> bool:
        nonlocal truncated, scratch_count
        if path.name in STRUCTURAL_BASENAMES:
            return True
        if path.suffix.lower() not in DISCOVERY_EXTENSIONS:
            return True
        try:
            stat = path.stat()
        except OSError:
            return True
        if stat.st_size > max_bytes:
            return True
        try:
            relative = path.relative_to(root)
        except ValueError:
            return True
        if is_scratch and scratch_count >= max_scratch_files:
            truncated = True
            return False
        if is_scratch:
            scratch_count += 1
        rel_posix = relative.as_posix()
        found.append(
            _new_candidate(
                source_id=None,
                provisional_id=f"local:{rel_posix}",
                paths=[rel_posix],
                primary_urls=[],
                identity_verified_claim=False,
                source_class="scratch" if is_scratch else _classify_relative(relative.parts),
            )
            | {
                "relative_path": rel_posix,
                "bytes": stat.st_size,
                "extension": path.suffix.lower(),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
        return True

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if name not in EXCLUDED_DIR_NAMES and name != ".work"
        )
        current = Path(dirpath)
        for filename in sorted(filenames):
            collect(current / filename, is_scratch=False)

    scratch_root = root / ".work"
    if scratch_root.is_dir():
        stop = False
        for dirpath, dirnames, filenames in os.walk(scratch_root):
            if stop:
                break
            dirnames[:] = sorted(name for name in dirnames if name not in EXCLUDED_DIR_NAMES)
            current = Path(dirpath)
            for filename in sorted(filenames):
                if not collect(current / filename, is_scratch=True):
                    stop = True
                    break
    return found, truncated


def discover_local_sources(
    repository: Path | str, *, max_bytes: int = DEFAULT_MAX_BYTES
) -> list[dict[str, Any]]:
    """Conservatively classify local files; never index them.

    Files below ``.work`` are reported as scratch. Registry-style files and
    repository tooling are reported as artifacts. Only unclassified document-like
    files become discovery candidates, and they still require identity validation
    before they can ever be indexed.
    """
    scanned, _truncated = scan_local_sources(repository, max_bytes=max_bytes)
    return scanned
