"""Boot-time identity of the loaded Document Forge authoring contracts."""

from __future__ import annotations

import hashlib
from pathlib import Path

DOCUMENT_RUNTIME_VERSION = "s36.v1"
_RUNTIME_FILES = (
    "authoring.py",
    "authoring_checkpoint.py",
    "authoring_protocol.py",
    "authoring_repair.py",
    "draft.py",
    "evidence.py",
    "evidence_bundle.py",
    "intent.py",
    "outline.py",
    "profile_contract.py",
    "rendering.py",
    "run_outcome.py",
    "section_parser.py",
    "skill_catalog.py",
    "skills.py",
    "visual_audit.py",
    "../subagents/pdf_generation.py",
    "../subagents/pdf_generation_runtime.py",
)


def compute_document_runtime_digest(root: Path | None = None) -> str:
    base = root or Path(__file__).resolve().parent
    digest = hashlib.sha256()
    digest.update(f"{DOCUMENT_RUNTIME_VERSION}\n".encode())
    for name in _RUNTIME_FILES:
        path = base / name
        digest.update(f"{name}\0".encode())
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


DOCUMENT_RUNTIME_DIGEST = compute_document_runtime_digest()


__all__ = [
    "DOCUMENT_RUNTIME_DIGEST",
    "DOCUMENT_RUNTIME_VERSION",
    "compute_document_runtime_digest",
]
