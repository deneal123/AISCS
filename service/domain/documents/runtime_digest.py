"""Boot-time identity of the loaded Document Forge authoring contracts."""

from __future__ import annotations

import hashlib
from pathlib import Path

DOCUMENT_RUNTIME_VERSION = "s36.v1"
_RUNTIME_FILES = (
    "authoring/execution.py",
    "authoring/checkpoint.py",
    "authoring/protocol.py",
    "authoring/repair.py",
    "semantic/draft.py",
    "semantic/editor.py",
    "evidence/citations.py",
    "evidence/bundle.py",
    "evidence/projection.py",
    "evidence/mentions.py",
    "evidence/registered_sources.py",
    "intent.py",
    "semantic/outline.py",
    "skills/profiles.py",
    "publisher_language.py",
    "semantic/rendering.py",
    "run_outcome.py",
    "semantic/section_parser.py",
    "skills/catalog.py",
    "skills/contracts.py",
    "visual_audit.py",
    "repair_provenance.py",
    "../subagents/pdf_generation.py",
    "../subagents/pdf_generation_runtime.py",
    "../../presentation/routers/capabilities/document_audit.py",
    "../../presentation/routers/capabilities/audit_usage_stream.py",
    "../../presentation/routers/agent/usage_checkpoint.py",
    "../../presentation/routers/capabilities/audit_checkpoint_barrier.py",
    "../../presentation/routers/capabilities/managed_document_audit.py",
    "../../infrastructure/document_audit/registry.py",
    "../../infrastructure/document_audit/process.py",
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
