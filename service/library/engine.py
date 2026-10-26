"""Library generations and retrieval: Book → Section → Chunk, separate from the evidence index.

The library owns its state directory (``.knowledge/library``), Neo4j label ``Library``
with a Russian fulltext analyzer and ``aspa_library_*`` Qdrant collections. The article
index (``.knowledge/active.json``, ``Knowledge`` nodes, ``aspa_research_*``) is never read
or written here.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core import DataError
from ..knowledge.corpus import (
    _PARAGRAPH_RE,
    _estimate_tokens,
    _pack_units,
    _split_oversized,
    _trim,
)
from ..knowledge.embedding import Embedder
from ..knowledge.engine import SAFE_ID, digest, validate_projection, writer_lock
from ..knowledge.settings import KnowledgeSettings
from ..knowledge.stores import GraphStore, VectorStore
from ..pipeline import atomic_write_json
from .catalog import citation, load_catalog
from .corpus import read_documents

CHUNKER_VERSION = "library-chunker-v1"
CHUNK_TARGET_TOKENS = 700
CHUNK_OVERLAP_TOKENS = 80
MIN_SEGMENT_CHARS = 1200
GRAPH_LABEL = "Library"
GRAPH_ANALYZER = "russian"
MAX_PER_BOOK = 3
_STEM_RE = re.compile(r"[^\W\d_]{3,}")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _stems(text: str) -> set[str]:
    """Crude prefix stems for the offline fallback; Neo4j applies real Russian stemming."""
    words = _STEM_RE.findall(text.casefold().replace("ё", "е"))
    return {w[:6] if len(w) > 6 else w for w in words}


def _units(text: str, start: int, end: int) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    hard_limit = CHUNK_TARGET_TOKENS * 4 * 2
    for match in _PARAGRAPH_RE.finditer(text, start, end):
        s, e = _trim(text, match.start(), match.end())
        if s >= e:
            continue
        pieces = (
            _split_oversized(text, s, e, CHUNK_TARGET_TOKENS)
            if _estimate_tokens(text[s:e]) > CHUNK_TARGET_TOKENS
            else [(s, e)]
        )
        for ps, pe in pieces:
            # A run-on "sentence" from a broken conversion is cut at whitespace.
            while pe - ps > hard_limit:
                cut = text.rfind(" ", ps + hard_limit // 4, ps + hard_limit // 2)
                if cut <= ps:
                    cut = ps + hard_limit // 2
                units.append(_trim(text, ps, cut))
                ps = cut
            units.append(_trim(text, ps, pe))
    return [(s, e) for s, e in units if s < e]


def _page_label(pages: list[dict[str, Any]], offset: int) -> str | None:
    if not pages:
        return None
    position = bisect_right([p["char"] for p in pages], offset) - 1
    return pages[position]["page"] if position >= 0 else pages[0]["page"]


def chunk_book(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Section-bounded paragraph packing with exact offsets into the normalized book."""
    text, sections, pages = document["text"], document["sections"], document["page_starts"]
    starts = sorted({0, *(s["char_start"] for s in sections)})
    spans = [(a, b) for a, b in zip(starts, [*starts[1:], len(text)], strict=True) if b > a]
    segments: list[tuple[int, int]] = []
    for a, b in spans:
        if segments and segments[-1][1] - segments[-1][0] < MIN_SEGMENT_CHARS:
            segments[-1] = (segments[-1][0], b)
        else:
            segments.append((a, b))
    section_starts = [s["char_start"] for s in sections]
    chunks: list[dict[str, Any]] = []
    for a, b in segments:
        units = _units(text, a, b)
        if not units:
            continue
        for start, end in _pack_units(text, units, CHUNK_TARGET_TOKENS, CHUNK_OVERLAP_TOKENS):
            position = bisect_right(section_starts, start) - 1
            section = sections[position] if position >= 0 else None
            chunks.append(
                {
                    "char_start": start,
                    "char_end": end,
                    "section_index": position if position >= 0 else None,
                    "section_path": section["path"] if section else [],
                    "page_start": _page_label(pages, start),
                    "page_end": _page_label(pages, max(start, end - 1)),
                    "text": text[start:end],
                }
            )
    for index, chunk in enumerate(chunks):
        text_hash = _sha(chunk["text"])
        chunk.update(
            chunk_id=f"{document['book_id']}::{document['sha256'][:12]}::{index:05d}"
            f"::{text_hash[:12]}",
            chunk_index=index,
            chunk_count=len(chunks),
            text_sha256=text_hash,
        )
    return chunks


def _edge(kind: str, source: str, target: str, book_id: str) -> dict[str, Any]:
    return {
        "id": "edge:" + digest([kind, source, target])[:24],
        "source": source,
        "target": target,
        "type": kind,
        "status": "verified",
        "provenance": {"book_id": book_id, "chunker": CHUNKER_VERSION},
    }


def project_library(catalog: dict[str, Any], documents: list[dict[str, Any]]) -> dict[str, Any]:
    books = {b["book_id"]: b for b in catalog["books"]}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for document in sorted(documents, key=lambda d: d["book_id"]):
        book_id = document["book_id"]
        book = books.get(book_id)
        if book is None or book["sha256"] != document["sha256"]:
            raise DataError("prepared book is not in the catalog: " + book_id)
        book_node = "book:" + book_id
        contents = [s["title"] for s in document["sections"] if s["level"] <= 2]
        nodes.append(
            {
                "id": book_node,
                "type": "Book",
                "text": citation(book) + "\n" + "; ".join(contents),
                "metadata": {
                    "book_id": book_id,
                    "citation": citation(book),
                    "title": book["title"],
                    "authors": book["authors"],
                    "year": book.get("year"),
                    "completeness": book["completeness"],
                    "format": book["format"],
                    "sha256": document["sha256"],
                    "text_sha256": document["text_sha256"],
                },
            }
        )
        section_ids: list[str] = []
        parents: list[tuple[int, str]] = []
        for index, section in enumerate(document["sections"]):
            node_id = f"section:{book_id}:{index:04d}"
            section_ids.append(node_id)
            while parents and parents[-1][0] >= section["level"]:
                parents.pop()
            nodes.append(
                {
                    "id": node_id,
                    "type": "Section",
                    "text": " › ".join(section["path"]),
                    "metadata": {
                        "book_id": book_id,
                        "level": section["level"],
                        "title": section["title"],
                        "path": section["path"],
                        "char_start": section["char_start"],
                        "char_end": section["char_end"],
                        "page": _page_label(document["page_starts"], section["char_start"]),
                    },
                }
            )
            edges.append(
                _edge("section_of", node_id, parents[-1][1] if parents else book_node, book_id)
            )
            parents.append((section["level"], node_id))
        header = citation(book) + (
            " (ознакомительный фрагмент)" if book["completeness"] == "fragment" else ""
        )
        previous: str | None = None
        for chunk in chunk_book(document):
            parent = (
                section_ids[chunk["section_index"]]
                if chunk["section_index"] is not None
                else book_node
            )
            nodes.append(
                {
                    "id": chunk["chunk_id"],
                    "type": "Chunk",
                    "text": chunk["text"],
                    "metadata": {
                        "book_id": book_id,
                        "doc_sha256": document["sha256"],
                        "text_sha256": chunk["text_sha256"],
                        "chunk_index": chunk["chunk_index"],
                        "chunk_count": chunk["chunk_count"],
                        "char_start": chunk["char_start"],
                        "char_end": chunk["char_end"],
                        "page_start": chunk["page_start"],
                        "page_end": chunk["page_end"],
                        "section_id": parent,
                        "section_path": chunk["section_path"],
                        "completeness": book["completeness"],
                        "embedding_header": header + "\n" + " › ".join(chunk["section_path"]),
                    },
                }
            )
            edges.append(_edge("fragment_of", chunk["chunk_id"], parent, book_id))
            if previous:
                edges.append(_edge("next", previous, chunk["chunk_id"], book_id))
            previous = chunk["chunk_id"]
    return {"nodes": nodes, "edges": edges}


class LibraryEngine:
    def __init__(self, project: Path, settings: KnowledgeSettings | None = None):
        self.project = Path(project)
        base = settings or KnowledgeSettings.from_env(self.project)
        library_dir = os.environ.get("RESEARCH_LIBRARY_DIR")
        self.settings = replace(
            base, state_dir=Path(library_dir) if library_dir else base.state_dir / "library"
        )
        self.state = self.settings.state_dir.resolve()
        self._read_cache: tuple[Any, ...] | None = None
        self._stem_cache: tuple[Any, ...] | None = None

    # -- state ---------------------------------------------------------------

    def _graph(self) -> GraphStore:
        return GraphStore(self.settings, label=GRAPH_LABEL, analyzer=GRAPH_ANALYZER)

    def _active(self) -> dict | None:
        path = self.state / "active.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def _generation(self, generation: str) -> Path:
        if not SAFE_ID.fullmatch(generation):
            raise DataError("invalid library generation ID")
        return self.state / "generations" / generation

    def _prepared(self) -> tuple[dict, list[dict]]:
        catalog = load_catalog(self.project)
        return catalog, read_documents(self.state)

    def _read(self) -> tuple[dict, dict | None, list[dict]]:
        active = self._active()
        if active is None:
            path = self.state / "corpus" / "documents.jsonl"
            stamp = ("prepared", path.stat().st_mtime_ns if path.exists() else None)
            if self._read_cache and self._read_cache[0] == stamp:
                return self._read_cache[1], None, self._read_cache[2]
            catalog, documents = self._prepared()
            projection = project_library(catalog, documents)
            self._read_cache = (stamp, projection, documents)
            return projection, None, documents
        directory = self._generation(active["generation"])
        path = directory / "projection.json"
        stat = path.stat()
        stamp = (active["generation"], active["projection_sha256"], stat.st_mtime_ns)
        if self._read_cache and self._read_cache[0] == stamp:
            return self._read_cache[1], active, self._read_cache[2]
        projection = json.loads(path.read_text(encoding="utf-8"))
        documents = json.loads((directory / "documents.json").read_text(encoding="utf-8"))
        if digest(projection) != active["projection_sha256"]:
            raise DataError("active library projection hash mismatch")
        if digest(documents) != active["documents_sha256"]:
            raise DataError("active library documents hash mismatch")
        self._read_cache = (stamp, projection, documents)
        return projection, active, documents

    @staticmethod
    def _embeddable(node: dict) -> bool:
        return node["type"] == "Chunk" and bool(node["text"].strip())

    @staticmethod
    def _embedding_input(node: dict) -> str:
        return node["metadata"]["embedding_header"] + "\n" + node["text"]

    # -- lifecycle -----------------------------------------------------------

    def prepare(self, *, download: bool = False, source_dir: Path | None = None) -> dict:
        from .corpus import prepare_library

        with writer_lock(self.state):
            return prepare_library(
                self.project, self.state, download=download, source_dir=source_dir
            )

    def build(self, *, offline: bool = False) -> dict:
        with writer_lock(self.state):
            catalog, documents = self._prepared()
            if not documents:
                raise DataError("no prepared books; run `library prepare` first")
            projection = project_library(catalog, documents)
            report = validate_projection(projection)
            if not report["ok"]:
                raise DataError("invalid library projection: " + str(report["errors"][:5]))
            identity = {
                "projection": projection,
                "model": self.settings.model,
                "dimension": self.settings.dimension,
                "documents_sha256": digest(documents),
                "catalog_sha256": catalog["catalog_sha256"],
                "chunker": CHUNKER_VERSION,
            }
            generation = "g-" + digest(identity)[:24]
            directory = self._generation(generation)
            existing = directory / "generation.json"
            if offline and existing.is_file():
                built = json.loads(existing.read_text(encoding="utf-8"))
                if built.get("ready") and not built.get("offline"):
                    return built  # same inputs, already indexed: never downgrade it
            directory.mkdir(parents=True, exist_ok=True)
            atomic_write_json(directory / "projection.json", projection, compact=True)
            atomic_write_json(directory / "documents.json", documents, compact=True)
            expected = [n for n in projection["nodes"] if self._embeddable(n)]
            info = {
                "generation": generation,
                "projection_sha256": digest(projection),
                "documents_sha256": digest(documents),
                "catalog_sha256": catalog["catalog_sha256"],
                "chunker": CHUNKER_VERSION,
                "model": self.settings.model,
                "dimension": self.settings.dimension,
                "collection": "aspa_library_" + generation.replace("-", "_"),
                "graph_label": GRAPH_LABEL,
                "books": len(documents),
                "chunks": len(expected),
                "offline": offline,
                "ready": False,
                **report,
            }
            atomic_write_json(directory / "generation.json", info)
            if offline:
                return info
            graph, vector = self._graph(), VectorStore(self.settings)
            graph.import_graph(generation, projection)
            vector.ensure(info["collection"])
            embedder = Embedder(self.settings)
            checkpoint = directory / "indexed.json"
            indexed = set(json.loads(checkpoint.read_text()) if checkpoint.exists() else [])
            pending = [n for n in expected if n["id"] not in indexed]
            for offset in range(0, len(pending), 16):
                batch = pending[offset : offset + 16]
                vectors = embedder.embed_many([self._embedding_input(n) for n in batch])
                vector.upsert_many(
                    info["collection"],
                    [(n["id"], v) for n, v in zip(batch, vectors, strict=True)],
                )
                indexed.update(n["id"] for n in batch)
                atomic_write_json(checkpoint, sorted(indexed))
            info["vectors_expected"] = len(expected)
            info["graph_counts"] = graph.counts(generation)
            info["vectors"] = vector.count(info["collection"])
            info["ready"] = info["graph_counts"] == {
                "nodes": report["nodes"],
                "edges": report["edges"],
            } and info["vectors"] == len(expected)
            atomic_write_json(directory / "generation.json", info)
            return info

    def publish(self, generation: str, *, allow_offline: bool = False) -> dict:
        with writer_lock(self.state):
            directory = self._generation(generation)
            info = json.loads((directory / "generation.json").read_text(encoding="utf-8"))
            if (
                info.get("generation") != generation
                or info.get("model") != self.settings.model
                or info.get("dimension") != self.settings.dimension
            ):
                raise DataError("library candidate model/dimension/generation mismatch")
            projection = json.loads((directory / "projection.json").read_text(encoding="utf-8"))
            documents = json.loads((directory / "documents.json").read_text(encoding="utf-8"))
            if (
                digest(projection) != info["projection_sha256"]
                or digest(documents) != info["documents_sha256"]
                or not validate_projection(projection)["ok"]
            ):
                raise DataError("library candidate failed validation")
            if not info["ready"] and not (allow_offline and info["offline"]):
                raise DataError("graph and vector indexes must be ready before publication")
            if not info["offline"]:
                from ..knowledge.verification import verify_backend_ids

                errors = verify_backend_ids(
                    self.settings, projection, info, self._embeddable, graph=self._graph()
                )
                if errors:
                    raise DataError("library candidate backend integrity: " + "; ".join(errors))
            previous = self._active()
            info["previous_generation"] = (
                previous.get("previous_generation")
                if previous and previous["generation"] == generation
                else previous["generation"]
                if previous
                else None
            )
            atomic_write_json(self.state / "active.json", info)
            self._read_cache = None
            return info

    def export(self, archive: Path | None = None) -> dict:
        """Portable snapshot of the published library (originals, texts, embedding cache)."""
        from ..knowledge.portable import CACHE, export_snapshot, write_record

        active = self._active()
        if not active or not active.get("ready"):
            raise DataError("publish an indexed library generation before exporting")
        catalog, documents = self._prepared()
        if (
            digest(documents) != active["documents_sha256"]
            or catalog["catalog_sha256"] != active["catalog_sha256"]
        ):
            raise DataError("catalog or prepared books differ from the published generation")
        members = [
            "corpus/documents.jsonl",
            "corpus/report.json",
            CACHE,
            *sorted({"corpus/objects/" + d["sha256"] for d in documents}),
        ]
        generation = active["generation"]
        target = archive or self.state.parent / "snapshots" / f"library-{generation}.zip"
        identity = {
            "generation": generation,
            "projection_sha256": active["projection_sha256"],
            "documents_sha256": active["documents_sha256"],
            "catalog_sha256": active["catalog_sha256"],
            "chunker": active["chunker"],
            "model": active["model"],
        }
        record = export_snapshot(self.state, members, target, index="library", identity=identity)
        write_record(self.project / "knowledge" / "library" / "snapshot.json", record)
        return record

    def restore(self, archive: Path, *, force: bool = False) -> dict:
        from ..knowledge.portable import check_record, read_manifest, restore_snapshot

        manifest = read_manifest(archive)
        with writer_lock(self.state):
            result = restore_snapshot(archive, self.state, index="library", force=force)
        warnings = [check_record(self.project / "knowledge" / "library" / "snapshot.json", archive)]
        if manifest.get("catalog_sha256") != load_catalog(self.project)["catalog_sha256"]:
            warnings.append("catalog differs from the snapshot; expect a new generation")
        result["warnings"] = [w for w in warnings if w]
        self._read_cache = None
        return result

    def rollback(self) -> dict:
        active = self._active()
        if not active or not active.get("previous_generation"):
            raise DataError("no previous library generation")
        previous = active["previous_generation"]
        info = json.loads(
            (self._generation(previous) / "generation.json").read_text(encoding="utf-8")
        )
        return self.publish(previous, allow_offline=info["offline"])

    def check(self, *, backends: bool = True) -> dict:
        projection, active, documents = self._read()
        errors: list[str] = []
        docs = {(d["book_id"], d["sha256"]): d for d in documents}
        for document in documents:
            raw = self.state / "corpus" / "objects" / document["sha256"]
            if not raw.is_file() or hashlib.sha256(raw.read_bytes()).hexdigest() != document[
                "sha256"
            ]:
                errors.append("raw book digest mismatch: " + document["book_id"])
            if _sha(document["text"]) != document["text_sha256"]:
                errors.append("normalized book digest mismatch: " + document["book_id"])
        chunks = 0
        for node in projection["nodes"]:
            if node["type"] != "Chunk":
                continue
            chunks += 1
            m = node["metadata"]
            doc = docs.get((m["book_id"], m["doc_sha256"]))
            if not doc or doc["text"][m["char_start"] : m["char_end"]] != node["text"]:
                errors.append("chunk locator does not resolve: " + node["id"])
        errors.extend(validate_projection(projection)["errors"])
        backend_checked = False
        if backends and active and active["ready"]:
            from ..knowledge.verification import verify_backend_ids

            backend_errors = verify_backend_ids(
                self.settings, projection, active, self._embeddable, graph=self._graph()
            )
            errors.extend(backend_errors)
            backend_checked = not backend_errors
        return {
            "ok": not errors,
            "errors": errors,
            "generation": active["generation"] if active else None,
            "books": len(documents),
            "chunks": chunks,
            "backend_ids_checked": backend_checked,
        }

    # -- reading -------------------------------------------------------------

    def status(self) -> dict:
        report_path = self.state / "corpus" / "report.json"
        report = (
            json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        )
        try:
            projection, active, documents = self._read()
            counts = Counter(n["type"] for n in projection["nodes"])
            books = len(documents)
        except DataError as exc:
            return {"mode": "unavailable", "error": str(exc), "state_dir": str(self.state)}
        if active:
            mode = "indexed" if active["ready"] else "published_offline"
        else:
            mode = "prepared_lexical" if books else "empty"
        return {
            "generation": active["generation"] if active else None,
            "mode": mode,
            "model": self.settings.model,
            "collection": active.get("collection") if active else None,
            "graph_label": GRAPH_LABEL,
            "index": {k: active.get(k) for k in ("ready", "vectors", "graph_counts")}
            if active
            else None,
            "books": books,
            "nodes": dict(counts),
            "prepared_warnings": {
                k: v["warnings"] for k, v in report.get("books", {}).items() if v["warnings"]
            },
            "prepare_errors": report.get("errors", {}),
            "separate_from": "knowledge evidence index (.knowledge/active.json)",
        }

    def books(self) -> dict:
        catalog = load_catalog(self.project)
        projection, active, documents = self._read()
        chunks = Counter(
            n["metadata"]["book_id"] for n in projection["nodes"] if n["type"] == "Chunk"
        )
        prepared = {d["book_id"]: d for d in documents}
        items = []
        for book in catalog["books"]:
            document = prepared.get(book["book_id"])
            items.append(
                {
                    "book_id": book["book_id"],
                    "citation": citation(book),
                    "title": book["title"],
                    "authors": book["authors"],
                    "year": book.get("year"),
                    "isbn": book.get("isbn", []),
                    "completeness": book["completeness"],
                    "format": book["format"],
                    "chunks": chunks.get(book["book_id"], 0),
                    "pages_available": bool(document and document["page_starts"]),
                    "contents": [
                        " › ".join(s["path"]) for s in document["sections"] if s["level"] <= 2
                    ]
                    if document
                    else [],
                    "notes": book.get("notes", ""),
                    "not_reported": sorted(book.get("field_resolution", {})),
                }
            )
        return {"generation": active["generation"] if active else None, "books": items}

    def _local_index(self, projection: dict) -> tuple[dict, Counter, dict, dict]:
        """Chunk stems for the fallback, plus section-title stems → first chunk of a section."""
        stamp = id(projection)
        if self._stem_cache and self._stem_cache[0] == stamp:
            return self._stem_cache[1:]
        chunks = sorted(
            (n for n in projection["nodes"] if n["type"] == "Chunk"),
            key=lambda n: (n["metadata"]["book_id"], n["metadata"]["chunk_index"]),
        )
        stems = {n["id"]: _stems(n["text"]) for n in chunks}
        frequency = Counter(s for values in stems.values() for s in values)
        by_book = defaultdict(list)
        for chunk in chunks:
            by_book[chunk["metadata"]["book_id"]].append(chunk)
        titles, first_chunk = {}, {}
        for node in projection["nodes"]:
            if node["type"] != "Section":
                continue
            m = node["metadata"]
            covering = next(
                (
                    c["id"]
                    for c in by_book[m["book_id"]]
                    if c["metadata"]["char_end"] > m["char_start"]
                ),
                None,
            )
            if covering:
                titles[node["id"]] = _stems(m["title"])
                first_chunk[node["id"]] = covering
        self._stem_cache = (stamp, stems, frequency, titles, first_chunk)
        return stems, frequency, titles, first_chunk

    def _section_titles(self, projection: dict, allowed: set[str], query: str) -> list[str]:
        """Navigation stream: chunks that open sections whose title the query names."""
        _, _, titles, first_chunk = self._local_index(projection)
        terms = _stems(query)
        scored = {}
        for section_id, title in titles.items():
            hit = terms & title
            chunk = first_chunk[section_id]
            if not hit or chunk not in allowed or len(hit) < 0.5 * len(title):
                continue
            score = len(hit) / len(title) + len(hit) / max(1, len(terms))
            scored[chunk] = max(score, scored.get(chunk, 0.0))
        return sorted(scored, key=lambda k: (-scored[k], k))

    def _lexical(self, projection: dict, allowed: list[str], query: str) -> list[str]:
        stems, frequency, _, _ = self._local_index(projection)
        total = max(1, len(stems))
        terms = _stems(query)
        scores = {}
        for node_id in allowed:
            hit = terms & stems.get(node_id, set())
            if hit:
                scores[node_id] = sum(math.log(1 + total / frequency[t]) for t in hit)
        return sorted(scores, key=lambda k: (-scores[k], k))

    def search(
        self,
        query: str,
        *,
        book_ids: list[str] | None = None,
        mode: str = "hybrid",
        limit: int = 8,
        max_per_book: int | None = None,
    ) -> dict:
        if not query.strip() or len(query) > 2000 or not 1 <= limit <= 50:
            raise DataError("query must be 1..2000 characters and limit 1..50")
        if mode not in {"hybrid", "lexical", "dense"}:
            raise DataError("mode must be hybrid, lexical or dense")
        projection, active, _ = self._read()
        nodes = {n["id"]: n for n in projection["nodes"]}
        known = {n["metadata"]["book_id"] for n in nodes.values() if n["type"] == "Book"}
        wanted = set(book_ids or [])
        if wanted - known:
            raise DataError("unknown book_ids: " + ", ".join(sorted(wanted - known)))
        allowed = sorted(
            k
            for k, n in nodes.items()
            if n["type"] == "Chunk" and (not wanted or n["metadata"]["book_id"] in wanted)
        )
        allowed_set = set(allowed)
        scope = allowed if wanted else None
        ready = bool(active and active["ready"])
        errors: list[str] = []
        lexical: list[str] | None = None
        dense: list[str] | None = None
        if ready and mode != "dense":
            try:
                found = self._graph().search(active["generation"], query, 200, allowed=scope)
                lexical = [k for k in found if k in allowed_set]
            except DataError:
                errors.append("graph_unavailable")
        if mode != "lexical":
            if ready:
                try:
                    found = VectorStore(self.settings).search(
                        active["collection"],
                        Embedder(self.settings).embed(query, query=True),
                        200,
                        allowed=scope,
                    )
                    dense = [k for k in found if k in allowed_set]
                except DataError:
                    errors.append("dense_unavailable")
            else:
                errors.append("dense_index_not_ready")
        graph_lexical = lexical is not None
        if lexical is None and (mode != "dense" or dense is None):
            lexical = self._lexical(projection, allowed, query)
        if dense is not None and graph_lexical:
            actual = "hybrid"
        elif dense is not None:
            actual = "dense" if lexical is None else "dense+fallback_lexical"
        else:
            actual = "neo4j_lexical" if graph_lexical else "library_lexical_fallback"
        sections = self._section_titles(projection, allowed_set, query) if mode != "dense" else []
        streams = [s for s in (dense, lexical, sections) if s]
        scores: dict[str, float] = defaultdict(float)
        for stream in streams:
            for rank, key in enumerate(stream):
                scores[key] += 1 / (60 + rank + 1)
        cap = max_per_book or (limit if len(wanted) == 1 else MAX_PER_BOOK)
        per_book: Counter = Counter()
        items = []
        for key in sorted(scores, key=lambda k: (-scores[k], k)):
            node = nodes[key]
            book_id = node["metadata"]["book_id"]
            if per_book[book_id] >= cap:
                continue
            per_book[book_id] += 1
            items.append(self._item(nodes, node, scores[key]))
            if len(items) == limit:
                break
        return {
            "items": items,
            "mode": actual,
            "errors": errors,
            "generation": active["generation"] if active else None,
            "query": query,
            "section_title_matches": len(sections),
            "note": "Методическая библиотека: советы авторов книг, не научные доказательства.",
        }

    @staticmethod
    def _pages(metadata: dict) -> str | None:
        start, end = metadata.get("page_start"), metadata.get("page_end")
        if start is None:
            return None
        return start if start == end else f"{start}–{end}"

    def _item(self, nodes: dict, node: dict, score: float | None = None) -> dict:
        m = node["metadata"]
        book = nodes["book:" + m["book_id"]]["metadata"]
        item = {
            "chunk_id": node["id"],
            "book_id": m["book_id"],
            "citation": book["citation"],
            "completeness": m["completeness"],
            "section_path": m["section_path"],
            "pages": self._pages(m),
            "char_start": m["char_start"],
            "char_end": m["char_end"],
            "text": node["text"],
        }
        if score is not None:
            item["retrieval_score"] = round(score, 6)
        return item

    def passage(self, chunk_id: str, *, context: int = 1) -> dict:
        if not 0 <= context <= 3:
            raise DataError("context must be between 0 and 3 neighbouring chunks")
        projection, active, documents = self._read()
        nodes = {n["id"]: n for n in projection["nodes"]}
        node = nodes.get(chunk_id)
        if node is None or node["type"] != "Chunk":
            raise DataError("library passage not found")
        m = node["metadata"]
        key = (m["book_id"], m["doc_sha256"])
        document = next((d for d in documents if (d["book_id"], d["sha256"]) == key), None)
        if document is None or document["text"][m["char_start"] : m["char_end"]] != node["text"]:
            raise DataError("passage no longer matches the registered book text")
        siblings = sorted(
            (
                n
                for n in nodes.values()
                if n["type"] == "Chunk" and n["metadata"]["book_id"] == m["book_id"]
            ),
            key=lambda n: n["metadata"]["chunk_index"],
        )
        index = m["chunk_index"]
        window = siblings[max(0, index - context) : index + context + 1]
        start = window[0]["metadata"]["char_start"]
        end = window[-1]["metadata"]["char_end"]
        return {
            **self._item(nodes, node),
            "generation": active["generation"] if active else None,
            "context": {
                "char_start": start,
                "char_end": end,
                "pages": self._pages(
                    {
                        "page_start": window[0]["metadata"]["page_start"],
                        "page_end": window[-1]["metadata"]["page_end"],
                    }
                ),
                "text": document["text"][start:end],
            },
            "previous_chunk_id": siblings[index - 1]["id"] if index > 0 else None,
            "next_chunk_id": siblings[index + 1]["id"] if index + 1 < len(siblings) else None,
        }

    def evaluate(self, suite: Path, *, mode: str = "hybrid") -> dict:
        cases = json.loads(suite.read_text(encoding="utf-8"))["cases"]
        rows = []
        for case in cases:
            started = time.perf_counter()
            result = self.search(case["query"], mode=mode, limit=5)
            found = [item["book_id"] for item in result["items"]]
            rows.append(
                {
                    "id": case["id"],
                    "hit": bool(set(found) & set(case["expected_books"])),
                    "returned_books": found,
                    "mode": result["mode"],
                    "errors": result["errors"],
                    "seconds": round(time.perf_counter() - started, 4),
                }
            )
        hits = sum(r["hit"] for r in rows)
        return {
            "cases": len(rows),
            "hits": hits,
            "recall_at_5": hits / len(rows) if rows else 0.0,
            "quality_ok": bool(rows) and hits / len(rows) >= 0.8,
            "requested_mode": mode,
            "all_backends_used": all(not r["errors"] for r in rows),
            "results": rows,
        }
