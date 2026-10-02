"""Read immutable applied review batches from directional bundles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .core import DataError, load_json


def read_batch(root: Path, scope: str, batch: Path | str) -> tuple[dict[str, Any], str]:
    """Prefer a live batch file, then a verified immutable bundle entry."""
    root = Path(root).resolve()
    candidate = Path(batch)
    if candidate.is_file():
        path = candidate.resolve()
        if not path.is_relative_to(root / "curation" / scope):
            raise DataError(f"review batch not found in {scope}: {path}")
        return load_json(path), str(path)
    name = candidate.name
    if not name.endswith(".json"):
        name += ".json"
    if candidate.name != str(batch):
        raise DataError(f"review batch must be a name or existing path: {batch}")
    bundle_path = root / "curation" / scope / "applied-batches.json"
    bundle = load_json(bundle_path) if bundle_path.is_file() else {"entries": {}, "id_index": {}}
    stored_name = name if name in bundle["entries"] else bundle["id_index"].get(name[:-5], name)
    entry = bundle["entries"].get(stored_name)
    if entry is None:
        path = root / "curation" / scope / "batches" / name
        if path.is_file():
            return load_json(path), str(path)
        raise DataError(f"review batch not found: {batch}")
    raw = entry["raw_json"].encode("utf-8")
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise DataError(f"review batch digest mismatch: {scope}/{name}")
    payload = json.loads(raw)
    if payload.get("meta", {}).get("batch_id") != bundle["entries"][stored_name]["batch_id"]:
        raise DataError(f"review batch ID mismatch: {scope}/{name}")
    return payload, f"{bundle_path.relative_to(root).as_posix()}#{stored_name}"


def applied_batch_names(root: Path, scope: str) -> list[str]:
    bundle_path = root / "curation" / scope / "applied-batches.json"
    if bundle_path.is_file():
        return sorted(load_json(bundle_path)["entries"])
    return sorted(path.name for path in (root / "curation" / scope / "batches").glob("*.json"))
