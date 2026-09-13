"""Boot-time identity of the loaded document compiler/profile contracts."""

from __future__ import annotations

import hashlib
from pathlib import Path

DOCUMENT_RUNTIME_VERSION = "s36.v1"
_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_FILES = (
    "domain/documents/audit.py",
    "domain/documents/contracts.py",
    "domain/documents/profiles.py",
    "application/documents/builds.py",
    "application/documents/checkpoints.py",
    "application/documents/sources.py",
    "presentation/routes/documents.py",
    "infrastructure/document_compiler.py",
)


def compute_document_runtime_digest(root: Path | None = None) -> str:
    base = root or _SERVICE_ROOT
    digest = hashlib.sha256()
    digest.update(f"{DOCUMENT_RUNTIME_VERSION}\n".encode())
    for relative in _RUNTIME_FILES:
        path = base / relative
        digest.update(f"{relative}\0".encode())
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


DOCUMENT_RUNTIME_DIGEST = compute_document_runtime_digest()


__all__ = [
    "DOCUMENT_RUNTIME_DIGEST",
    "DOCUMENT_RUNTIME_VERSION",
    "compute_document_runtime_digest",
]
