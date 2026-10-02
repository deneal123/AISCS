"""Map cached primary texts conservatively, then build a registered corpus.

Never use worker summaries as article text. Title/identifier matching is repeated
by the corpus importer before any artifact enters the searchable corpus.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import defaultdict
from pathlib import Path

from pypdf import PdfReader

from service.core import ResearchRepository
from service.knowledge.corpus import parse_document, prepare_corpus
from service.pipeline import atomic_write_json


def normalize(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def discover(repository: ResearchRepository) -> list[dict]:
    root = repository.data_dir.parent
    sources = {s["id"]: s for s in repository.bundle().records["sources"]}
    titles = {s: normalize(r["название"]) for s, r in sources.items()}
    pmids = {
        str(r["identifiers"]["pmid"]): s for s, r in sources.items() if r["identifiers"].get("pmid")
    }
    candidates = defaultdict(list)
    excluded = {"verify", ".venv", "node_modules", "__pycache__", "kb-20261002"}
    # Explicit source IDs and PMID caches narrow candidates before reading large files.
    for path in (root / ".work").rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".pdf", ".xml", ".html", ".txt"}:
            continue
        if set(path.parts) & excluded or path.name in {"result.md", "coordinator-status.md"}:
            continue
        if "pi-workers" in path.parts and "raw" not in path.parts:
            continue
        if "logs" in path.parts and path.suffix.lower() == ".txt":
            continue
        if not 200 <= path.stat().st_size <= 25 * 1024 * 1024:
            continue
        hinted = set(re.findall(r"(?i)\bs\d{3,}\b", str(path)))
        hinted = {s.upper() for s in hinted} & sources.keys()
        if path.parent.name in {"arts", "abs"} and path.stem in pmids:
            hinted.add(pmids[path.stem])
        if not hinted and path.parent != root / ".work":
            continue
        try:
            if path.suffix.lower() == ".pdf":
                reader = PdfReader(path)
                parsed = {"text": "\n".join(p.extract_text() or "" for p in reader.pages[:2])}
            else:
                parsed = parse_document(path.read_bytes()[:200000], suffix=path.suffix.lower())
        except Exception:
            continue
        if parsed.get("error_page") or parsed.get("needs_ocr"):
            continue
        front = normalize(parsed.get("text", "")[:6000])
        possible = hinted or sources.keys()
        for source_id in possible:
            if sources[source_id]["validation"]["status"] == "rejected":
                continue
            if titles[source_id] and titles[source_id] in front:
                candidates[source_id].append(
                    {
                        "source_id": source_id,
                        "path": str(path),
                        "primary_url": sources[source_id]["identifiers"].get("exact_url"),
                        "bytes": path.stat().st_size,
                    }
                )
    # Prefer complete longer bodies; importer validates each candidate independently.
    return [
        {k: v for k, v in item.items() if k != "bytes"}
        for source_id in sorted(candidates)
        for item in sorted(candidates[source_id], key=lambda item: -item["bytes"])[:3]
    ]


def main() -> None:
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    repository = ResearchRepository()
    root = repository.data_dir.parent
    candidates = discover(repository)
    atomic_write_json(root / ".work" / "knowledge-candidates.json", candidates)
    result = prepare_corpus(
        repository, root / ".knowledge", candidates=candidates, download=args.download
    )
    manifest = result["manifest"]
    # Machine-independent tracked locator map; private paths remain in runtime state.
    for entry in manifest["entries"]:
        entry["paths"] = [Path(p).relative_to(root).as_posix() for p in entry["paths"]]
        entry["completeness"] = "unavailable"
    documents_path = root / ".knowledge" / "corpus" / "documents.jsonl"
    documents = [
        json.loads(line) for line in documents_path.read_text(encoding="utf-8").splitlines()
    ]
    by_id = {doc["source_id"]: doc for doc in documents}
    for entry in manifest["entries"]:
        if entry["source_id"] in by_id:
            entry["completeness"] = by_id[entry["source_id"]]["completeness"]
    atomic_write_json(root / "knowledge" / "corpus-manifest.json", manifest)
    print(json.dumps({"candidates": len(candidates), "counts": result["counts"]}, indent=2))


if __name__ == "__main__":
    main()
