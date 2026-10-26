"""Export and restore of the evidence-index snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..common.errors import DataError
from ..indexing.snapshots import (
    CACHE,
    check_record,
    export_snapshot,
    read_manifest,
    restore_snapshot,
    write_record,
)


def export_knowledge(engine, archive: Path | None = None) -> dict[str, Any]:
    """Snapshot the published evidence index; reading it never changes the index."""
    from ..indexing.generations import digest

    active = engine._active()
    if not active or not active.get("ready"):
        raise DataError("publish an indexed knowledge generation before exporting")
    corpus = engine.state / "corpus"
    documents = [
        json.loads(line)
        for line in (corpus / "documents.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    if digest(documents) != active["documents_sha256"] or digest(manifest) != active.get(
        "corpus_sha256"
    ):
        raise DataError("prepared corpus differs from the published generation")
    members = [
        "corpus/documents.jsonl",
        "corpus/manifest.json",
        CACHE,
        *sorted({"corpus/objects/" + d["sha256"] for d in documents}),
    ]
    generation = active["generation"]
    target = archive or engine.state / "snapshots" / f"knowledge-{generation}.zip"
    identity = {
        "generation": generation,
        "projection_sha256": active["projection_sha256"],
        "documents_sha256": active["documents_sha256"],
        "corpus_sha256": active["corpus_sha256"],
        "model": active["model"],
        "data_fingerprint": engine.repository.bundle().fingerprint,
    }
    record = export_snapshot(engine.state, members, target, index="knowledge", identity=identity)
    write_record(engine.project / "knowledge" / "snapshot.json", record)
    return record


def restore_knowledge(engine, archive: Path, *, force: bool = False) -> dict[str, Any]:
    from ..indexing.generations import writer_lock

    manifest = read_manifest(archive)
    with writer_lock(engine.state):
        result = restore_snapshot(archive, engine.state, index="knowledge", force=force)
    warnings = [check_record(engine.project / "knowledge" / "snapshot.json", archive)]
    if manifest.get("data_fingerprint") != engine.repository.bundle().fingerprint:
        warnings.append("canonical data differ from the snapshot; expect a new generation")
    result["warnings"] = [w for w in warnings if w]
    return result
