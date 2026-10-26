"""Library preparation: pin originals by SHA-256, normalize books, report text quality.

Originals are read from the catalog ``source_dir`` (or downloaded only with explicit
``download=True``) and kept as content-addressed objects in the library state directory.
Nothing here touches the article corpus in ``.knowledge/corpus``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..core import DataError
from ..knowledge.corpus import _atomic_write_bytes, _atomic_write_text, _fetch
from ..pipeline import atomic_write_json
from .catalog import load_catalog
from .formats import PARSER_VERSION, extract

DOWNLOAD_MAX_BYTES = 64 * 1024 * 1024
DOWNLOAD_TIMEOUT_S = 180.0


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_documents(state: Path) -> list[dict[str, Any]]:
    """Load normalized books and re-verify both raw and normalized digests."""
    path = state / "corpus" / "documents.jsonl"
    if not path.is_file():
        return []
    documents = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    for document in documents:
        raw = state / "corpus" / "objects" / document["sha256"]
        if not raw.is_file() or _sha256(raw.read_bytes()) != document["sha256"]:
            raise DataError("library object hash mismatch: " + document["book_id"])
        if _sha256(document["text"].encode()) != document["text_sha256"]:
            raise DataError("normalized book hash mismatch: " + document["book_id"])
    return documents


def quality(document: dict[str, Any], book: dict[str, Any]) -> dict[str, Any]:
    text = document["text"]
    letters = [ch for ch in text if ch.isalpha()]
    cyrillic = sum("Ѐ" <= ch <= "ӿ" for ch in letters)
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    report = {
        "chars": len(text),
        "paragraphs": len(paragraphs),
        "max_paragraph_chars": max((len(p) for p in paragraphs), default=0),
        "sections": len(document["sections"]),
        "pages": len(document["page_starts"]),
        "replacement_chars": text.count("�"),
        "cyrillic_ratio": round(cyrillic / len(letters), 4) if letters else 0.0,
        "excluded_sections": document["excluded_sections"],
        "warnings": [],
    }
    if report["replacement_chars"]:
        report["warnings"].append("decoding produced replacement characters")
    if report["cyrillic_ratio"] < 0.85:
        report["warnings"].append("low share of Cyrillic letters")
    if not report["sections"]:
        report["warnings"].append("no section structure recovered")
    detected = "fragment" if document["fragment_detected"] else "full_text"
    if detected == "fragment" and book["completeness"] != "fragment":
        report["warnings"].append("file ends with a retailer preview mark")
    return report


def _original(book: dict[str, Any], source_dir: Path, objects: Path, download: bool) -> bytes:
    cached = objects / book["sha256"]
    if cached.is_file():
        data = cached.read_bytes()
        if _sha256(data) == book["sha256"]:
            return data
        raise DataError(book["book_id"] + ": cached object hash mismatch")
    origin = book["origin"]
    if origin["kind"] == "file":
        path = source_dir / origin["file"]
        if not path.is_file():
            raise DataError(book["book_id"] + ": original not found in source_dir")
        data = path.read_bytes()
    elif not download:
        raise DataError(book["book_id"] + ": remote original absent; rerun with --download")
    else:
        response = _fetch(
            origin["url"], timeout=DOWNLOAD_TIMEOUT_S, max_bytes=DOWNLOAD_MAX_BYTES
        )
        if not response["ok"]:
            raise DataError(book["book_id"] + ": download failed: " + str(response["error"]))
        data = response["body"]
    if _sha256(data) != book["sha256"]:
        raise DataError(book["book_id"] + ": original differs from the catalog sha256")
    _atomic_write_bytes(cached, data)
    return data


def prepare_library(
    project: Path, state: Path, *, download: bool = False, source_dir: Path | None = None
) -> dict[str, Any]:
    """Normalize every catalog book into ``corpus/documents.jsonl`` with a quality report."""
    catalog = load_catalog(project)
    source = (source_dir or project / catalog["source_dir"]).resolve()
    corpus = state / "corpus"
    objects = corpus / "objects"
    documents: list[dict[str, Any]] = []
    reports: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for book in catalog["books"]:
        try:
            data = _original(book, source, objects, download)
            result = extract(book["format"], data, options=book.get("options"))
        except DataError as exc:
            errors[book["book_id"]] = str(exc)
            continue
        document = {
            "book_id": book["book_id"],
            "sha256": book["sha256"],
            "format": book["format"],
            "parser_version": PARSER_VERSION,
            "tool": result["tool"],
            "completeness": book["completeness"],
            "fragment_detected": result["fragment"],
            "file_metadata": result["metadata"],
            "excluded_sections": result["excluded_sections"],
            "sections": result["sections"],
            "page_starts": result["page_starts"],
            "text": result["text"],
            "text_sha256": _sha256(result["text"].encode()),
        }
        documents.append(document)
        reports[book["book_id"]] = quality(document, book)
    corpus.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        corpus / "documents.jsonl",
        "".join(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n" for d in documents),
    )
    report = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "catalog_sha256": catalog["catalog_sha256"],
        "parser_version": PARSER_VERSION,
        "books": reports,
        "errors": errors,
    }
    atomic_write_json(corpus / "report.json", report)
    return {
        "ok": not errors,
        "books": len(documents),
        "errors": errors,
        "warnings": {k: v["warnings"] for k, v in reports.items() if v["warnings"]},
        "report": str(corpus / "report.json"),
    }
