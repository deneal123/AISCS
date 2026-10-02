"""Pi extraction proposals: quote validation is separate from scientific acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..core import DataError

RELATIONS = frozenset(
    {
        "uses_method",
        "uses_dataset",
        "measures",
        "reports_result",
        "qualified_by",
        "cites",
        "compares_with",
        "contradicts",
    }
)
ENTITY_TYPES = frozenset(
    {"Method", "Model", "Dataset", "Population", "Construct", "Result", "Limitation", "Source"}
)


def integrate_extractions(projection: dict, path: Path, state_dir: Path) -> None:
    documents_path = state_dir / "corpus" / "documents.jsonl"
    documents = (
        [
            json.loads(line)
            for line in documents_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if documents_path.exists()
        else []
    )
    document_index = {(d["source_id"], d["sha256"]): d for d in documents}
    nodes = {n["id"]: n for n in projection["nodes"]}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        proposal = json.loads(line)
        doc = document_index.get((proposal.get("source_id"), proposal.get("document_sha256")))
        if doc is None or doc["source_id"] != proposal.get("source_id"):
            raise DataError("extraction document identity/hash mismatch")
        quote = proposal.get("quote", "")
        start, end = proposal.get("start"), proposal.get("end")
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end
            or doc["text"][start:end] != quote
        ):
            raise DataError("extraction quote does not match exact document offsets")
        review = proposal.get("review", {})
        if review.get("status") == "rejected":
            continue
        if review.get("status") not in {"unreviewed", "accepted"}:
            raise DataError("extraction review status invalid")
        accepted = review.get("status") == "accepted"
        if accepted and not all(review.get(k) for k in ("reviewer", "date", "rationale")):
            raise DataError("accepted extraction lacks scientific review record")
        source = nodes.get(doc["source_id"])
        if source is None or proposal.get("relation") not in RELATIONS:
            raise DataError("extraction has unknown source or relationship")
        if proposal.get("claim_type") not in {
            "methodological",
            "reported",
            "observed",
            "limitation",
            "secondary_report",
        }:
            raise DataError("extraction lacks an explicit claim type")
        if source["validation_status"] == "rejected" and accepted:
            raise DataError("rejected source cannot supply accepted extraction")
        entity = proposal.get("entity", {})
        if entity.get("type") not in ENTITY_TYPES or not entity.get("name"):
            raise DataError("extraction entity type/name invalid")
        identity = entity.get("identifier")
        if identity and not identity.startswith(("doi:", "accession:", "dataset:")):
            raise DataError("extraction identity requires an explicit identifier namespace")
        if identity and identity.split(":", 1)[1].casefold() not in doc["text"].casefold():
            raise DataError("entity identifier is not supported by registered text")
        # Identifier-free mentions remain document-scoped; name matching does not merge entities.
        node_id = (
            "entity:"
            + hashlib.sha256(
                json.dumps(
                    [entity["type"], identity or [doc["sha256"], entity["name"]]],
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()[:24]
        )
        status = "verified" if accepted else "unreviewed"
        locator = {
            "source_id": doc["source_id"],
            "document_sha256": doc["sha256"],
            "start": start,
            "end": end,
            "quote": quote,
            "primary_url": doc.get("primary_url"),
            "review": review,
            "claim_type": proposal.get("claim_type", "reported"),
            "scope": proposal.get("scope_note", proposal.get("scope", "")),
        }
        if node_id not in nodes:
            node = {
                "id": node_id,
                "type": entity["type"],
                "text": entity["name"],
                "source_ids": [doc["source_id"]],
                "metadata": entity,
                "locators": [locator],
                "validation_status": status,
                "limitations": source["limitations"],
                "permitted_conclusion": source["permitted_conclusion"],
            }
            projection["nodes"].append(node)
            nodes[node_id] = node
        else:
            node = nodes[node_id]
            node["source_ids"] = sorted(set(node["source_ids"]) | {doc["source_id"]})
            node["locators"].append(locator)
            if accepted:
                node["validation_status"] = "verified"
        edge_id = "edge:" + hashlib.sha256(line.encode()).hexdigest()[:24]
        projection["edges"].append(
            {
                "id": edge_id,
                "source": doc["source_id"],
                "target": node_id,
                "type": proposal["relation"],
                "provenance": locator,
                "status": status,
            }
        )
