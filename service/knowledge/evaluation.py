"""Fixed retrieval benchmark; report actual coverage, mode, latency and failures."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .engine import KnowledgeEngine


def evaluate(engine: KnowledgeEngine, suite: Path, *, mode: str = "hybrid") -> dict:
    cases = json.loads(suite.read_text(encoding="utf-8"))["cases"]
    rows = []
    for case in cases:
        start = time.perf_counter()
        result = engine.search(case["query"], mode=mode, limit=10)
        found = {
            s
            for hit in result["items"]
            if hit["type"] in {"Source", "Chunk", "EvidenceRow", "Claim"}
            for s in hit["source_ids"]
        }
        rows.append(
            {
                "id": case["id"],
                "hit": bool(found & set(case["expected_sources"])),
                "mode": result["mode"],
                "generation": result["generation"],
                "errors": result["errors"],
                "seconds": round(time.perf_counter() - start, 4),
                "returned_sources": sorted(found),
            }
        )
    hits = sum(row["hit"] for row in rows)
    return {
        "cases": len(rows),
        "hits": hits,
        "recall_at_10": hits / len(rows),
        "quality_ok": hits / len(rows) >= 0.9,
        "requested_mode": mode,
        "all_backends_used": all(not row["errors"] for row in rows),
        "generations": sorted({row["generation"] for row in rows if row["generation"]}),
        "results": rows,
    }
