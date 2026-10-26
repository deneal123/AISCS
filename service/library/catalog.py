"""Tracked book catalog: identity, provenance and parsing options of every book."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..common.errors import DataError
from .formats import FORMATS

BOOK_ID = re.compile(r"^B\d{3}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMPLETENESS = frozenset({"full_text", "fragment"})
RESOLUTIONS = frozenset({"reported", "not_reported", "not_applicable", "unavailable_after_search"})
OPTIONS = frozenset(
    {
        "exclude_sections",
        "toc",
        "inline_headings",
        "max_heading_level",
        "pdf_layout",
        "join_split_words",
    }
)
NULLABLE_FIELDS = ("year", "publisher", "city")


def catalog_path(project: Path) -> Path:
    return project / "knowledge" / "library" / "catalog.json"


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    books = catalog.get("books")
    if catalog.get("schema_version") != "1.0.0" or not isinstance(books, list):
        return ["catalog must have schema_version 1.0.0 and a books list"]
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    for book in books:
        book_id = str(book.get("book_id", ""))
        where = book_id or "<missing id>"
        if not BOOK_ID.fullmatch(book_id) or book_id in seen_ids:
            errors.append(f"{where}: book_id must be unique B###")
        seen_ids.add(book_id)
        if not str(book.get("title", "")).strip() or not book.get("authors"):
            errors.append(f"{where}: title and authors are required")
        if book.get("format") not in FORMATS:
            errors.append(f"{where}: unsupported format")
        if book.get("completeness") not in COMPLETENESS:
            errors.append(f"{where}: completeness must be full_text or fragment")
        digest = str(book.get("sha256", ""))
        if not SHA256.fullmatch(digest) or digest in seen_hashes:
            errors.append(f"{where}: sha256 must be a unique lowercase hex digest")
        seen_hashes.add(digest)
        origin = book.get("origin") or {}
        if origin.get("kind") == "file":
            if not origin.get("file") or Path(origin["file"]).name != origin["file"]:
                errors.append(f"{where}: file origin must name a file inside source_dir")
        elif origin.get("kind") == "url":
            if not str(origin.get("url", "")).startswith(("http://", "https://")):
                errors.append(f"{where}: url origin needs an http(s) URL")
            if not origin.get("retrieved_at"):
                errors.append(f"{where}: url origin needs retrieved_at")
        else:
            errors.append(f"{where}: origin.kind must be file or url")
        unknown = set(book.get("options") or {}) - OPTIONS
        if unknown:
            errors.append(f"{where}: unknown options {sorted(unknown)}")
        resolution = book.get("field_resolution") or {}
        for name, entry in resolution.items():
            if entry.get("status") not in RESOLUTIONS or not entry.get("reason"):
                errors.append(f"{where}: field_resolution.{name} needs status and reason")
        for name in NULLABLE_FIELDS:
            if book.get(name) in (None, "") and name not in resolution:
                errors.append(f"{where}: null {name} needs field_resolution")
        if not book.get("isbn") and "isbn" not in resolution:
            errors.append(f"{where}: empty isbn needs field_resolution")
        for item in (book.get("options") or {}).get("toc", []):
            if not isinstance(item.get("page"), int) or item.get("level") not in {1, 2, 3, 4}:
                errors.append(f"{where}: toc entries need integer page and level 1..4")
                break
        if (book.get("options") or {}).get("pdf_layout", "pages") not in {"pages", "spreads"}:
            errors.append(f"{where}: pdf_layout must be pages or spreads")
    return errors


def load_catalog(project: Path) -> dict[str, Any]:
    path = catalog_path(project)
    try:
        raw = path.read_bytes()
        catalog = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise DataError("library catalog is missing or invalid JSON") from exc
    errors = validate_catalog(catalog)
    if errors:
        raise DataError("invalid library catalog: " + "; ".join(errors[:5]))
    catalog["catalog_sha256"] = hashlib.sha256(raw).hexdigest()
    return catalog


def citation(book: dict[str, Any]) -> str:
    """Short human citation; absent imprint fields are omitted, never guessed."""
    imprint = ", ".join(str(book[k]) for k in ("city", "publisher", "year") if book.get(k))
    return f"{', '.join(book['authors'])}. {book['title']}" + (f". {imprint}" if imprint else "")
