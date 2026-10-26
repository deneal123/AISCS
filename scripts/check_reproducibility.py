"""Snapshots rebuild their recorded generations from the embedding cache alone.

Each archive named by ``knowledge/snapshot.json`` and ``knowledge/library/snapshot.json``
is restored into an empty temporary state directory and rebuilt with in-memory graph
and vector stores. Any provider call fails the check; live Neo4j and Qdrant are never
touched. Archives live outside Git (``.knowledge/snapshots``); missing ones are reported
as skipped. ``--renormalize`` re-parses the library originals from the snapshot before
building, which also proves the book normalizers unchanged (needs antiword for .doc).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from service.common.errors import DataError  # noqa: E402
from service.indexing.embedding import Embedder  # noqa: E402
from service.indexing.settings import KnowledgeSettings  # noqa: E402
from service.knowledge import engine as knowledge_engine  # noqa: E402
from service.knowledge.snapshot import restore_knowledge  # noqa: E402
from service.library import engine as library_engine  # noqa: E402
from service.registry.repository import ResearchRepository  # noqa: E402

SNAPSHOTS = ROOT / ".knowledge" / "snapshots"


class MemoryGraph:
    def __init__(self, settings, *, label="Knowledge", analyzer=""):
        self.label = label
        self.nodes: list[str] = []
        self.edges: list[str] = []

    def import_graph(self, generation, projection):
        self.nodes = [n["id"] for n in projection["nodes"]]
        self.edges = [e["id"] for e in projection["edges"]]
        MemoryGraph.last = self

    def counts(self, generation):
        return {"nodes": len(MemoryGraph.last.nodes), "edges": len(MemoryGraph.last.edges)}


class MemoryVectors:
    points: set[str] = set()

    def __init__(self, settings):
        pass

    def ensure(self, collection):
        MemoryVectors.points = set()

    def upsert_many(self, collection, rows):
        MemoryVectors.points.update(key for key, _ in rows)

    def count(self, collection):
        return len(MemoryVectors.points)


def _no_provider(self, route, payload):
    raise DataError("provider call attempted while rebuilding a snapshot: " + route)


def _rebuild(name: str, record_path: Path, restore, build) -> dict:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    archive = SNAPSHOTS / record["archive"]
    if not archive.is_file():
        return {"index": name, "skipped": f"archive not found: {archive.name}"}
    restored = restore(archive)
    info = build()
    return {
        "index": name,
        "expected": record["generation"],
        "rebuilt": info["generation"],
        "ready": info["ready"],
        "vectors": info.get("vectors"),
        "warnings": restored.get("warnings", []),
        "ok": info["generation"] == record["generation"] and info["ready"],
    }


def main() -> int:
    renormalize = "--renormalize" in sys.argv[1:]
    Embedder.request = _no_provider
    for module in (knowledge_engine, library_engine):
        module.GraphStore = MemoryGraph
        module.VectorStore = MemoryVectors
    results = []
    workspace = tempfile.TemporaryDirectory(prefix="aspa-repro-", ignore_cleanup_errors=True)
    with workspace as tmp:
        base = Path(tmp)
        os.environ["RESEARCH_LIBRARY_DIR"] = str(base / "library")
        library = library_engine.LibraryEngine(ROOT, KnowledgeSettings(base / "unused"))

        def build_library() -> dict:
            if renormalize:
                library.prepare()
            return library.build()

        library_record = ROOT / "knowledge/library/snapshot.json"
        results.append(_rebuild("library", library_record, library.restore, build_library))
        knowledge = knowledge_engine.KnowledgeEngine(
            ResearchRepository(ROOT / "data"), KnowledgeSettings(base / "knowledge")
        )
        results.append(
            _rebuild(
                "knowledge",
                ROOT / "knowledge/snapshot.json",
                lambda archive: restore_knowledge(knowledge, archive),
                knowledge.build,
            )
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r.get("ok", True) for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
