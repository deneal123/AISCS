"""Generation identity and write-safety primitives shared by both indexes."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from ..common.errors import DataError
from ..common.jsonio import atomic_write_json

SAFE_ID = re.compile(r"^g-[0-9a-f]{24}$")


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def validate_projection(projection: dict) -> dict:
    errors = []
    ids = [n["id"] for n in projection["nodes"]]
    if len(ids) != len(set(ids)):
        errors.append("duplicate graph node IDs")
    known = set(ids)
    edges = projection["edges"]
    if len({e["id"] for e in edges}) != len(edges):
        errors.append("duplicate graph edge IDs")
    for edge in edges:
        if edge["source"] not in known or edge["target"] not in known:
            errors.append("dangling edge " + edge["id"])
        if edge.get("status") not in {"verified", "unreviewed"} or not edge.get("provenance"):
            errors.append("edge lacks review status/provenance " + edge["id"])
    return {"ok": not errors, "errors": errors, "nodes": len(ids), "edges": len(edges)}


@contextmanager
def writer_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "writer.lock"
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise DataError(
            "knowledge writer already active; inspect writer.lock before recovery"
        ) from exc
    try:
        with handle:
            yield
    finally:
        path.unlink(missing_ok=True)


class GenerationStore:
    """Active pointer and generation directories of one index state directory.

    ``label`` names the index in error messages ("knowledge", "library").
    """

    def __init__(self, state: Path, label: str):
        self.state = state
        self.label = label

    def active(self) -> dict | None:
        path = self.state / "active.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def directory(self, generation: str) -> Path:
        if not SAFE_ID.fullmatch(generation):
            raise DataError(f"invalid {self.label} generation ID")
        return self.state / "generations" / generation

    def info(self, generation: str) -> dict:
        path = self.directory(generation) / "generation.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def activate(self, info: dict) -> dict:
        """Point ``active.json`` at a verified candidate, keeping one rollback step."""
        previous = self.active()
        info["previous_generation"] = (
            previous.get("previous_generation")
            if previous and previous["generation"] == info["generation"]
            else previous["generation"]
            if previous
            else None
        )
        atomic_write_json(self.state / "active.json", info)
        return info

    def previous(self) -> str:
        active = self.active()
        if not active or not active.get("previous_generation"):
            raise DataError(f"no previous {self.label} generation")
        return active["previous_generation"]


def index_vectors(
    vector,
    embedder,
    collection: str,
    nodes: list[dict],
    input_of: Callable[[dict], str],
    checkpoint: Path,
    *,
    batch_size: int = 16,
) -> None:
    """Embed and upsert nodes in bounded batches; ``checkpoint`` lets a build resume."""
    indexed = set(json.loads(checkpoint.read_text()) if checkpoint.exists() else [])
    pending = [node for node in nodes if node["id"] not in indexed]
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        vectors = embedder.embed_many([input_of(node) for node in batch])
        vector.upsert_many(
            collection, [(node["id"], v) for node, v in zip(batch, vectors, strict=True)]
        )
        indexed.update(node["id"] for node in batch)
        atomic_write_json(checkpoint, sorted(indexed))
