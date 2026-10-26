"""Atomic file writes through a temporary sibling."""

from __future__ import annotations

from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via a temporary sibling inside ``state_dir`` (never a root scratch file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))
