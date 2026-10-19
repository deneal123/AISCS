"""Boot-time identity of the loaded document compiler/profile contracts."""

from __future__ import annotations

import hashlib
from pathlib import Path

DOCUMENT_RUNTIME_VERSION = "s36.v2"
_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_FILES = (
    "domain/files.py",
    "domain/documents/audit.py",
    "domain/documents/font_audit.py",
    "domain/documents/source_identity.py",
    "domain/documents/project_validation.py",
    "domain/documents/contracts.py",
    "domain/documents/profiles.py",
    "application/documents/builds.py",
    "application/documents/artifact_integrity.py",
    "application/documents/registry_retention.py",
    "application/lifecycle.py",
    "application/documents/admission.py",
    "application/documents/build_store.py",
    "application/documents/visual_transitions.py",
    "application/documents/build_preparation.py",
    "application/documents/projects.py",
    "application/documents/checkpoints.py",
    "application/documents/checkpoint_storage.py",
    "application/documents/sources.py",
    "application/documents/source_exchange.py",
    "application/documents/source_recovery.py",
    "presentation/routes/documents.py",
    "infrastructure/document_compiler.py",
    "drivers/docker_cli.py",
    "infrastructure/document_cleanup.py",
    "infrastructure/document_processes.py",
    "infrastructure/document_output_runtime.py",
    "infrastructure/document_report.py",
    "domain/documents/runtime_digest.py",
)
_RUNTIME_DATA_GLOBS = ("domain/documents/profile_data/**/*",)


def compute_document_runtime_digest(root: Path | None = None) -> str:
    base = root or _SERVICE_ROOT
    digest = hashlib.sha256()
    digest.update(f"{DOCUMENT_RUNTIME_VERSION}\n".encode())
    files = set(_RUNTIME_FILES)
    for pattern in _RUNTIME_DATA_GLOBS:
        files.update(
            path.relative_to(base).as_posix() for path in base.glob(pattern) if path.is_file()
        )
    for relative in sorted(files):
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
