"""Backend identity checks: Neo4j and Qdrant hold exactly a generation's IDs."""

from __future__ import annotations

from .stores import GraphStore, VectorStore


def verify_backend_ids(
    settings, projection: dict, info: dict, embeddable, *, graph=None
) -> list[str]:
    """Check candidate identities, not merely counts, before switching the pointer."""
    errors = []
    nodes = {n["id"]: n for n in projection["nodes"]}
    try:
        graph = graph or GraphStore(settings)
        label = getattr(graph, "label", "Knowledge")
        actual = graph.query(
            f"MATCH (n:{label} {{generation:$generation}}) RETURN n.id AS id",
            generation=info["generation"],
        )
        if {r["id"] for r in actual} != set(nodes):
            errors.append("Neo4j node IDs differ from projection")
        actual_edges = graph.query(
            f"MATCH (n:{label} {{generation:$generation}})-[r:LINK]->() RETURN r.id AS id",
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
