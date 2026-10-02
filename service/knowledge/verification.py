"""Independent corpus, JSON-pointer and backend identity verification."""

from __future__ import annotations

import hashlib
import json

from .stores import GraphStore, VectorStore


def verify(engine, *, backends: bool = True) -> dict:
    projection, active = engine._read()
    errors, files, pointers = [], {}, set()
    nodes = {n["id"]: n for n in projection["nodes"]}
    sources = {n["id"] for n in nodes.values() if n["type"] == "Source"}
    expected = {s["id"] for s in engine.repository.bundle().records["sources"]}
    if sources != expected:
        errors.append("source coverage differs from canonical registry")
    for n in nodes.values():
        if set(n["source_ids"]) - sources:
            errors.append("unknown source ID in " + n["id"])
    document_path = engine.state / "corpus" / "documents.jsonl"
    documents = (
        [json.loads(x) for x in document_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        if document_path.exists()
        else []
    )
    if active:
        document_path = engine._generation(active["generation"]) / "documents.json"
        documents = json.loads(document_path.read_text(encoding="utf-8"))
    docs = {(d["source_id"], d["sha256"]): d for d in documents}
    for document in documents:
        path = engine.state / "corpus" / "objects" / document["sha256"]
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != document["sha256"]:
            errors.append("raw document digest mismatch: " + document["source_id"])
        if hashlib.sha256(document["text"].encode()).hexdigest() != document["text_sha256"]:
            errors.append("normalized document digest mismatch: " + document["source_id"])
    for n in nodes.values():
        if n["type"] == "Chunk":
            m = n["metadata"]
            doc = docs.get((n["source_ids"][0], m["doc_sha256"]))
            if not doc or doc["text"][m["char_start"] : m["char_end"]] != n["text"]:
                errors.append("chunk locator does not resolve: " + n["id"])
        for loc in n["locators"]:
            if isinstance(loc, dict) and loc.get("json_locator"):
                pointers.add(loc["json_locator"])
    for e in projection["edges"]:
        if e["provenance"].get("json_locator"):
            pointers.add(e["provenance"]["json_locator"])
    checked = 0
    for locator in sorted(pointers):
        filename, sep, pointer = locator.partition("#")
        if not filename.startswith("data/") or not sep:
            continue
        relative = filename.removeprefix("data/")
        path = (engine.repository.data_dir / relative).resolve()
        if not path.is_relative_to(engine.repository.data_dir.resolve()):
            errors.append("JSON locator escapes data directory")
            continue
        try:
            if filename not in files:
                files[filename] = json.loads(path.read_text(encoding="utf-8"))
            obj = files[filename]
            if pointer and not pointer.startswith("/"):
                continue  # Existing named locators retain their established resolver.
            for raw in pointer.split("/")[1:]:
                key = raw.replace("~1", "/").replace("~0", "~")
                obj = obj[int(key)] if isinstance(obj, list) else obj[key]
            checked += 1
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            errors.append("JSON locator does not resolve: " + locator)
    backend_ids_checked = False
    if backends and active and active["ready"]:
        backend_errors = verify_backend_ids(engine.settings, projection, active, engine._embeddable)
        errors.extend(backend_errors)
        backend_ids_checked = not backend_errors
    return {
        "ok": not errors,
        "errors": errors,
        "generation": active["generation"] if active else None,
        "sources": len(sources),
        "documents": len(documents),
        "json_pointers_checked": checked,
        "backend_ids_checked": backend_ids_checked,
    }


def verify_backend_ids(settings, projection: dict, info: dict, embeddable) -> list[str]:
    """Check candidate identities, not merely counts, before switching the pointer."""
    errors = []
    nodes = {n["id"]: n for n in projection["nodes"]}
    try:
        graph = GraphStore(settings)
        actual = graph.query(
            "MATCH (n:Knowledge {generation:$generation}) RETURN n.id AS id",
            generation=info["generation"],
        )
        if {r["id"] for r in actual} != set(nodes):
            errors.append("Neo4j node IDs differ from projection")
        actual_edges = graph.query(
            "MATCH (n:Knowledge {generation:$generation})-[r:LINK]->() RETURN r.id AS id",
            generation=info["generation"],
        )
        if {r["id"] for r in actual_edges} != {e["id"] for e in projection["edges"]}:
            errors.append("Neo4j edge IDs differ from projection")
        vector = VectorStore(settings)
        dimension = vector.request("GET", "/collections/" + info["collection"])["result"][
            "config"
        ]["params"]["vectors"]["size"]
        if dimension != settings.dimension:
            errors.append("Qdrant dimension differs from pinned model")
        actual_vectors, offset = set(), None
        while True:
            payload = {"limit": 256, "with_payload": True, "with_vector": False}
            if offset is not None:
                payload["offset"] = offset
            page = vector.request(
                "POST", "/collections/" + info["collection"] + "/points/scroll", json=payload
            )["result"]
            actual_vectors.update(p["payload"]["node_id"] for p in page["points"])
            offset = page.get("next_page_offset")
            if offset is None:
                break
        if actual_vectors != {n["id"] for n in nodes.values() if embeddable(n)}:
            errors.append("Qdrant node IDs differ from projection")
    except Exception as exc:
        errors.append("backend verification failed: " + type(exc).__name__)
    return errors
