"""Generation lifecycle and bounded evidence retrieval shared by HTTP, MCP and CLI."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from ..core import DataError, ResearchRepository
from ..pipeline import atomic_write_json
from .embedding import Embedder
from .settings import KnowledgeSettings
from .stores import GraphStore, VectorStore

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


class KnowledgeEngine:
    def __init__(self, repository: ResearchRepository, settings: KnowledgeSettings | None = None):
        self.repository = repository
        self.settings = settings or KnowledgeSettings.from_env(repository.data_dir.parent)
        self.state = self.settings.state_dir.resolve()
        self.project = Path(
            os.environ.get("RESEARCH_KNOWLEDGE_PROJECT", repository.data_dir.parent)
        )
        self._read_cache = None

    def _projection(self) -> dict:
        from .projection import project

        return project(self.repository)

    def _active(self) -> dict | None:
        path = self.state / "active.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def _generation(self, generation: str) -> Path:
        if not SAFE_ID.fullmatch(generation):
            raise DataError("invalid knowledge generation ID")
        return self.state / "generations" / generation

    def _read(self) -> tuple[dict, dict | None]:
        active = self._active()  # Capture once: every component uses this same generation.
        if active is None:
            return self._projection(), None
        directory = self._generation(active["generation"])
        path = directory / "projection.json"
        stat = path.stat()
        stamp = (active["generation"], active["projection_sha256"], stat.st_mtime_ns, stat.st_size)
        if self._read_cache and self._read_cache[0] == stamp:
            return self._read_cache[1], active
        payload = json.loads(path.read_text(encoding="utf-8"))
        if digest(payload) != active["projection_sha256"]:
            raise DataError("active knowledge projection hash mismatch")
        self._read_cache = (stamp, payload)
        return payload, active

    def build(self, *, offline: bool = False) -> dict:
        from .corpus import chunk_documents

        with writer_lock(self.state):
            projection = self._projection()
            documents = []
            documents_path = self.state / "corpus" / "documents.jsonl"
            if documents_path.is_file():
                documents = [
                    json.loads(line)
                    for line in documents_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                for document in documents:
                    raw = self.state / "corpus" / "objects" / document["sha256"]
                    if (
                        not raw.is_file()
                        or hashlib.sha256(raw.read_bytes()).hexdigest() != document["sha256"]
                    ):
                        raise DataError("corpus object hash mismatch")
                    if (
                        hashlib.sha256(document["text"].encode()).hexdigest()
                        != document["text_sha256"]
                    ):
                        raise DataError("normalized document hash mismatch")
                self._attach_documents(projection, documents)
                self._attach_chunks(projection, chunk_documents(documents))
            self._attach_extractions(projection)
            if not offline:
                self._fit_inputs(projection)
            manifest_path = self.state / "corpus" / "manifest.json"
            corpus = (
                json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.exists()
                else None
            )
            report = validate_projection(projection)
            if not report["ok"]:
                raise DataError("invalid knowledge projection: " + str(report["errors"][:5]))
            generation = (
                "g-"
                + digest(
                    {
                        "projection": projection,
                        "model": self.settings.model,
                        "dimension": self.settings.dimension,
                        "documents_sha256": digest(documents),
                        "corpus_sha256": digest(corpus),
                    }
                )[:24]
            )
            directory = self._generation(generation)
            directory.mkdir(parents=True, exist_ok=True)
            atomic_write_json(directory / "projection.json", projection, compact=True)
            atomic_write_json(directory / "documents.json", documents, compact=True)
            atomic_write_json(directory / "corpus.json", corpus, compact=True)
            names = defaultdict(list)
            for node in projection["nodes"]:
                if node["type"] in {
                    "Method",
                    "Model",
                    "Dataset",
                    "Population",
                    "Construct",
                    "Source",
                }:
                    name = (
                        node["metadata"].get("title", node["text"])
                        if node["type"] == "Source"
                        else node["text"]
                    )
                    normalized = " ".join(re.findall(r"\w+", name.casefold()))
                    if normalized and normalized not in {"unknown", "not reported", "null"}:
                        names[(node["type"], normalized)].append(node["id"])
            proposals = [
                {
                    "kind": kind,
                    "name": name,
                    "entity_ids": sorted(ids),
                    "status": "unreviewed",
                    "reason": "Name equality proposes review; no identity merge is applied.",
                }
                for (kind, name), ids in sorted(names.items())
                if len(ids) > 1
            ]
            atomic_write_json(directory / "merge-proposals.json", proposals, compact=True)
            info = {
                "generation": generation,
                "projection_sha256": digest(projection),
                "model": self.settings.model,
                "dimension": self.settings.dimension,
                "documents_sha256": digest(documents),
                "corpus_sha256": digest(corpus),
                "merge_proposals": len(proposals),
                "collection": "aspa_research_" + generation.replace("-", "_"),
                "offline": offline,
                "ready": False,
                **report,
            }
            atomic_write_json(directory / "generation.json", info)
            if offline:
                return info
            graph, vector = GraphStore(self.settings), VectorStore(self.settings)
            graph.import_graph(generation, projection)
            vector.ensure(info["collection"])
            embedder = Embedder(self.settings)
            checkpoint = directory / "indexed.json"
            indexed = set(json.loads(checkpoint.read_text()) if checkpoint.exists() else [])
            expected = [n for n in projection["nodes"] if self._embeddable(n)]
            pending = [node for node in expected if node["id"] not in indexed]
            titles = {
                n["id"]: n["metadata"].get("title", "")
                for n in projection["nodes"]
                if n["type"] == "Source"
            }
            for offset in range(0, len(pending), 16):
                batch = pending[offset : offset + 16]
                inputs = [
                    "\n".join(
                        [titles.get(n["source_ids"][0], "") if n["source_ids"] else "", n["text"]]
                    )
                    for n in batch
                ]
                embeddings = embedder.embed_many(inputs)
                vector.upsert_many(
                    info["collection"],
                    [
                        (node["id"], embedding)
                        for node, embedding in zip(batch, embeddings, strict=True)
                    ],
                )
                indexed.update(node["id"] for node in batch)
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

    @staticmethod
    def _embeddable(node: dict) -> bool:
        return (
            not node.get("metadata", {}).get("embedding_excluded")
            and bool(node["text"].strip())
            and node["type"].lower()
            in {
                "source",
                "claim",
                "evidencerow",
                "resource",
                "variant",
                "chunk",
                "cluster",
                "passage",
                "model",
            }
        )

    def _fit_inputs(self, projection: dict) -> None:
        """Split exceptional tokenizer-heavy spans without deleting any parent text."""
        embedder = Embedder(self.settings)
        titles = {
            n["id"]: n["metadata"].get("title", "")
            for n in projection["nodes"]
            if n["type"] == "Source"
        }
        pending = [n for n in projection["nodes"] if self._embeddable(n)]
        for offset in range(0, len(pending), 16):
            batch = pending[offset : offset + 16]
            inputs = [
                "\n".join(
                    [titles.get(n["source_ids"][0], "") if n["source_ids"] else "", n["text"]]
                )
                for n in batch
            ]
            for parent, count in zip(batch, embedder.count_many(inputs), strict=True):
                if count <= self.settings.context_tokens:
                    continue
                parent["metadata"]["embedding_excluded"] = True
                stack = [(0, len(parent["text"]))]
                while stack:
                    start, end = stack.pop(0)
                    body = parent["text"][start:end]
                    header = titles.get(parent["source_ids"][0], "") if parent["source_ids"] else ""
                    if embedder.token_count(header + "\n" + body) > self.settings.context_tokens:
                        if end - start < 2:
                            raise DataError("embedding header exceeds context")
                        middle = start + (end - start) // 2
                        stack[0:0] = [(start, middle), (middle, end)]
                        continue
                    child = deepcopy(parent)
                    child["id"] = "segment:" + digest([parent["id"], start, end])[:24]
                    child["text"] = body
                    child["type"] = "Chunk" if parent["type"] == "Chunk" else "Passage"
                    child["metadata"].pop("embedding_excluded", None)
                    child["metadata"].update(
                        parent_id=parent["id"], parent_start=start, parent_end=end
                    )
                    if parent["type"] == "Chunk":
                        child["metadata"].update(
                            char_start=parent["metadata"]["char_start"] + start,
                            char_end=parent["metadata"]["char_start"] + end,
                            text_sha256=hashlib.sha256(body.encode()).hexdigest(),
                        )
                        child["locators"] = [child["metadata"]]
                    projection["nodes"].append(child)
                    projection["edges"].append(
                        {
                            "id": "edge:" + digest(child["id"]),
                            "source": child["id"],
                            "target": parent["id"],
                            "type": "fragment_of",
                            "status": "verified",
                            "provenance": {"parent_id": parent["id"], "start": start, "end": end},
                        }
                    )

    def publish(self, generation: str, *, allow_offline: bool = False) -> dict:
        with writer_lock(self.state):
            directory = self._generation(generation)
            info = json.loads((directory / "generation.json").read_text(encoding="utf-8"))
            if (
                info.get("generation") != generation
                or info.get("model") != self.settings.model
                or info.get("dimension") != self.settings.dimension
            ):
                raise DataError("knowledge candidate model/dimension/generation mismatch")
            projection = json.loads((directory / "projection.json").read_text(encoding="utf-8"))
            if (
                digest(projection) != info["projection_sha256"]
                or not validate_projection(projection)["ok"]
            ):
                raise DataError("knowledge candidate failed validation")
            documents = json.loads((directory / "documents.json").read_text(encoding="utf-8"))
            if digest(documents) != info["documents_sha256"]:
                raise DataError("knowledge candidate documents failed validation")
            if info.get("corpus_sha256"):
                corpus = json.loads((directory / "corpus.json").read_text(encoding="utf-8"))
                if digest(corpus) != info["corpus_sha256"]:
                    raise DataError("knowledge candidate corpus registry hash mismatch")
            for document in documents:
                raw = self.state / "corpus" / "objects" / document["sha256"]
                if (
                    not raw.is_file()
                    or hashlib.sha256(raw.read_bytes()).hexdigest() != document["sha256"]
                    or hashlib.sha256(document["text"].encode()).hexdigest()
                    != document["text_sha256"]
                ):
                    raise DataError("knowledge candidate corpus hash mismatch")
            if not info["ready"] and not (allow_offline and info["offline"]):
                raise DataError("both graph and vector indexes must be ready before publication")
            if not info["offline"]:
                counts = GraphStore(self.settings).counts(generation)
                if (
                    counts != info["graph_counts"]
                    or VectorStore(self.settings).count(info["collection"])
                    != info["vectors_expected"]
                ):
                    raise DataError("knowledge backends changed since candidate validation")
                from .verification import verify_backend_ids

                errors = verify_backend_ids(self.settings, projection, info, self._embeddable)
                if errors:
                    raise DataError("knowledge candidate backend integrity: " + "; ".join(errors))
            previous = self._active()
            info["previous_generation"] = (
                previous.get("previous_generation")
                if previous and previous["generation"] == generation
                else previous["generation"]
                if previous
                else None
            )
            atomic_write_json(self.state / "active.json", info)
            return info

    def rollback(self) -> dict:
        active = self._active()
        if not active or not active.get("previous_generation"):
            raise DataError("no previous knowledge generation")
        previous = active["previous_generation"]
        info = json.loads(
            (self._generation(previous) / "generation.json").read_text(encoding="utf-8")
        )
        return self.publish(previous, allow_offline=info["offline"])

    def status(self) -> dict:
        projection, active = self._read()

        def coverage(manifest):
            if manifest is None:
                return None
            entries = manifest["entries"]
            return {
                "sources": len(entries),
                "statuses": dict(Counter(e["status"] for e in entries)),
            }

        manifest_path = self.state / "corpus" / "manifest.json"
        prepared = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists()
            else None
        )
        frozen = None
        if active and active.get("corpus_sha256"):
            frozen = json.loads(
                (self._generation(active["generation"]) / "corpus.json").read_text(encoding="utf-8")
            )
            if digest(frozen) != active["corpus_sha256"]:
                raise DataError("published corpus registry hash mismatch")
        unreviewed = [e for e in projection["edges"] if e["status"] == "unreviewed"]
        pi_unreviewed = sum("review" in e["provenance"] for e in unreviewed)
        return {
            "generation": active["generation"] if active else None,
            "mode": "indexed" if active and active["ready"] else "canonical_lexical",
            "model": self.settings.model,
            "dimension": self.settings.dimension,
            "index": {
                k: active.get(k) for k in ("ready", "vectors", "graph_counts", "documents_sha256")
            }
            if active
            else None,
            "provider_configured": bool(self.settings.gateway_key),
            "identity_merge_proposals": active.get("merge_proposals", 0) if active else 0,
            "projection": validate_projection(projection),
            "corpus": coverage(frozen),
            "published_corpus": coverage(frozen),
            "prepared_corpus": coverage(prepared),
            "unreviewed_canonical_edges": len(unreviewed) - pi_unreviewed,
            "unreviewed_pi_edges": pi_unreviewed,
            "unreviewed_edges": sum(e["status"] == "unreviewed" for e in projection["edges"]),
            "scientific_gate": "G0_REVISE",
            "saturation": False,
        }

    @staticmethod
    def _allowed(node: dict, filters: dict, include_unreviewed: bool) -> bool:
        if node["type"] in {"Alias", "ExternalReference"} and "type" not in filters:
            return False
        if node.get("validation_status") in {"rejected", "unreviewed"} and not include_unreviewed:
            return False
        metadata = node.get("metadata", {})
        for key, value in filters.items():
            if key not in {"target_construct", "subject_domain", "type", "source_id"}:
                raise DataError("unsupported knowledge filter: " + key)
            actual = node.get("type") if key == "type" else metadata.get(key)
            if key == "source_id":
                actual = node["source_ids"]
            if value != actual and not (isinstance(actual, list) and value in actual):
                return False
        return True

    def search(
        self,
        query: str,
        *,
        filters: dict | None = None,
        mode: str = "hybrid",
        limit: int = 10,
        include_unreviewed: bool = False,
    ) -> dict:
        if not 1 <= limit <= 100 or len(query) > 2000 or mode not in {"hybrid", "lexical", "dense"}:
            raise DataError("invalid knowledge search parameters")
        projection, active = self._read()
        nodes = {n["id"]: n for n in projection["nodes"]}
        from .terminology import expand

        retrieval_query = expand(query)
        allowed = {
            k for k, n in nodes.items() if self._allowed(n, filters or {}, include_unreviewed)
        }
        terms = set(re.findall(r"\w+", retrieval_query.casefold()))
        lexical = sorted(
            allowed, key=lambda k: (-sum(1 for t in terms if t in nodes[k]["text"].casefold()), k)
        )
        lexical = [k for k in lexical if any(t in nodes[k]["text"].casefold() for t in terms)]
        errors, streams = [], []
        actual_mode = "canonical_lexical"
        if active and active["ready"]:
            try:
                lexical = [
                    k
                    for k in GraphStore(self.settings).search(
                        active["generation"], retrieval_query, 500, allowed=sorted(allowed)
                    )
                    if k in allowed
                ]
                actual_mode = "neo4j_lexical"
            except DataError:
                errors.append("graph_unavailable")
            if mode != "lexical":
                try:
                    dense = VectorStore(self.settings).search(
                        active["collection"],
                        Embedder(self.settings).embed(retrieval_query, query=True),
                        500,
                        allowed=sorted(allowed),
                    )
                    streams.append([k for k in dense if k in allowed])
                    actual_mode = "hybrid" if mode == "hybrid" else "dense"
                except DataError:
                    errors.append("dense_unavailable")
        elif mode != "lexical":
            errors.append("dense_index_not_ready")
        if mode != "dense" or not streams:
            streams.append(lexical)
        matches = {}
        if not filters or not ({"source_id", "type"} & set(filters)):
            diverse = []
            for stream in streams:
                seen, grouped = set(), []
                for key in stream:
                    refs = nodes[key]["source_ids"]
                    identity = refs[0] if len(refs) == 1 and refs[0] in allowed else key
                    if identity not in seen:
                        seen.add(identity)
                        grouped.append(identity)
                        matches.setdefault(identity, key)
                diverse.append(grouped)
            streams = diverse
        scores = defaultdict(float)
        for stream in streams:
            for rank, key in enumerate(stream):
                scores[key] += 1 / (60 + rank + 1)
        aliases = {n["text"]: n["source_ids"][0] for n in nodes.values() if n["type"] == "Alias"}
        exact_id = aliases.get(query.strip(), query.strip())
        exact = nodes.get(exact_id) if nodes.get(exact_id, {}).get("type") == "Source" else None
        if not exact:
            for source in nodes.values():
                if source["type"] != "Source":
                    continue
                identifiers = source["metadata"].get("identifiers", {})
                needle = query.strip().removeprefix("doi:").casefold()
                if needle in {str(v).casefold() for v in identifiers.values() if v}:
                    exact = source
                    break
        if exact and exact["id"] in allowed:
            scores[exact["id"]] += 1
        ordered = sorted(scores, key=lambda k: (-scores[k], k))
        # One primary source per family, but claims and attached chunks remain inspectable.
        families, selected = set(), []
        version_of = {
            e["source"]: e["target"]
            for e in projection["edges"]
            if e["type"].lower() == "version_of" and e["status"] == "verified"
        }
        for key in ordered:
            family, visited = key, set()
            while family in version_of and family not in visited:
                visited.add(family)
                family = version_of[family]
            if nodes[key]["type"].lower() == "source" and family in families:
                continue
            if nodes[key]["type"].lower() == "source":
                families.add(family)
            citations = [
                {
                    "source_id": sid,
                    "title": nodes[sid]["metadata"].get("title"),
                    **nodes[sid]["metadata"].get("identifiers", {}),
                }
                for sid in nodes[key]["source_ids"]
                if sid in nodes
            ]
            selected.append(
                {
                    **nodes[key],
                    "retrieval_score": scores[key],
                    "sources": citations,
                    "matched_evidence": nodes[matches[key]]
                    if key in matches and matches[key] != key
                    else None,
                }
            )
            if len(selected) == limit:
                break
        return {
            "items": selected,
            "mode": actual_mode,
            "errors": errors,
            "generation": active["generation"] if active else None,
            "query": query,
            "retrieval_query": retrieval_query,
        }

    def evidence(self, node_id: str, *, include_unreviewed: bool = False) -> dict:
        projection, active = self._read()
        aliases = {
            n["text"]: n["source_ids"][0] for n in projection["nodes"] if n["type"] == "Alias"
        }
        node_id = aliases.get(node_id, node_id)
        node = next((n for n in projection["nodes"] if n["id"] == node_id), None)
        if node is None or (
            node.get("validation_status") in {"unreviewed", "rejected"} and not include_unreviewed
        ):
            node = None
        if node is None:
            raise DataError("knowledge evidence not found")
        result = {
            "node": node,
            "generation": active["generation"] if active else None,
            "sources": [
                n["metadata"].get("record", n)
                for n in projection["nodes"]
                if n["id"] in node["source_ids"]
            ],
        }
        if node["type"] == "Chunk":
            metadata = node["metadata"]
            doc_hash = metadata.get("doc_sha256")
            path = (
                self._generation(active["generation"]) / "documents.json"
                if active
                else self.state / "corpus" / "documents.jsonl"
            )
            if path.exists():
                registered = (
                    json.loads(path.read_text(encoding="utf-8"))
                    if active
                    else [
                        json.loads(line)
                        for line in path.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                )
                if active and digest(registered) != active["documents_sha256"]:
                    raise DataError("active generation document hash mismatch")
                for doc in registered:
                    if doc["sha256"] == doc_hash and doc["source_id"] in node["source_ids"]:
                        start, end = metadata["char_start"], metadata["char_end"]
                        if doc["text"][start:end] != node["text"]:
                            raise DataError("evidence span no longer matches registered document")
                        result["document"] = {
                            "sha256": doc_hash,
                            "text_sha256": doc["text_sha256"],
                            "primary_url": doc.get("primary_url"),
                            "completeness": doc["completeness"],
                            "context": doc["text"][max(0, start - 300) : end + 300],
                            "start": start,
                            "end": end,
                        }
                        break
        return result

    def graph(
        self,
        node_id: str,
        *,
        depth: int = 1,
        edge_types: list[str] | None = None,
        include_unreviewed: bool = False,
    ) -> dict:
        if not 0 <= depth <= 2:
            raise DataError("graph depth must be between zero and two")
        projection, active = self._read()
        aliases = {
            n["text"]: n["source_ids"][0] for n in projection["nodes"] if n["type"] == "Alias"
        }
        node_id = aliases.get(node_id, node_id)
        nodes = {n["id"]: n for n in projection["nodes"]}
        if node_id not in nodes or (
            nodes[node_id].get("validation_status") in {"unreviewed", "rejected"}
            and not include_unreviewed
        ):
            raise DataError("graph entity not found")
        reached, selected = {node_id}, {}
        for _ in range(depth):
            next_ids = set()
            for edge in projection["edges"]:
                if not include_unreviewed and (
                    edge["status"] in {"unreviewed", "rejected"}
                    or any(
                        nodes[k].get("validation_status") in {"unreviewed", "rejected"}
                        for k in (edge["source"], edge["target"])
                    )
                ):
                    continue
                if edge_types and edge["type"] not in edge_types:
                    continue
                if edge["source"] in reached or edge["target"] in reached:
                    selected[edge["id"]] = edge
                    next_ids.update((edge["source"], edge["target"]))
            reached.update(next_ids)
            if len(reached) > 500:
                raise DataError("graph expansion exceeds 500 nodes; filter edge types")
        return {
            "nodes": [nodes[k] for k in sorted(reached)],
            "edges": list(selected.values()),
            "generation": active["generation"] if active else None,
        }

    def _attach_documents(self, projection: dict, documents: list[dict]) -> None:
        sources = {n["id"]: n for n in projection["nodes"] if n["type"] == "Source"}
        for doc in documents:
            source = sources.get(doc["source_id"])
            if source is None:
                raise DataError("document references unknown source")
            identity = "document:" + doc["source_id"] + ":" + doc["sha256"]
            metadata = {k: v for k, v in doc.items() if k not in {"text", "origin"}}
            for field in ("subject_domain", "target_construct"):
                if field in source["metadata"]:
                    metadata[field] = source["metadata"][field]
            locator = {
                "source_id": doc["source_id"],
                "doc_sha256": doc["sha256"],
                "primary_url": doc.get("primary_url"),
                "text_sha256": doc["text_sha256"],
            }
            projection["nodes"].append(
                {
                    "id": identity,
                    "type": "Document",
                    "text": source["metadata"].get("title", doc.get("title") or "Registered text"),
                    "source_ids": [doc["source_id"]],
                    "metadata": metadata,
                    "locators": [locator],
                    "validation_status": "rejected"
                    if source["validation_status"] == "rejected"
                    else "registered_text",
                    "limitations": source["limitations"],
                    "permitted_conclusion": source["permitted_conclusion"],
                }
            )
            projection["edges"].append(
                {
                    "id": "edge:" + digest(identity),
                    "source": identity,
                    "target": doc["source_id"],
                    "type": "document_of",
                    "status": "verified",
                    "provenance": locator,
                }
            )

    def _attach_chunks(self, projection: dict, chunks: list[dict]) -> None:
        for chunk in chunks:
            coordinates = {k: v for k, v in chunk.items() if k != "text"}
            source_id = chunk["source_id"]
            source = next((n for n in projection["nodes"] if n["id"] == source_id), None)
            if source is None:
                raise DataError("chunk references unknown source")
            node_id = chunk.get("chunk_id", chunk.get("id", "chunk:" + digest(chunk)))
            document_id = "document:" + source_id + ":" + chunk["doc_sha256"]
            projection["nodes"].append(
                {
                    "id": node_id,
                    "type": "Chunk",
                    "text": chunk["text"],
                    "source_ids": [source_id],
                    "metadata": {
                        **{
                            k: source["metadata"][k]
                            for k in ("subject_domain", "target_construct")
                            if k in source["metadata"]
                        },
                        **coordinates,
                    },
                    "locators": [coordinates],
                    "validation_status": "rejected"
                    if source["validation_status"] == "rejected"
                    else "registered_text",
                    "limitations": source["limitations"],
                    "permitted_conclusion": source["permitted_conclusion"],
                }
            )
            projection["edges"].append(
                {
                    "id": "edge:" + digest([node_id, source_id]),
                    "source": node_id,
                    "target": document_id,
                    "type": "fragment_of",
                    "provenance": coordinates,
                    "status": "verified",
                }
            )

    def _attach_extractions(self, projection: dict) -> None:
        from .extraction import integrate_extractions

        path = self.project / "knowledge" / "extractions.jsonl"
        if path.exists():
            integrate_extractions(projection, path, self.state)
