"""Text normalization, format detection and small corpus helpers."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ...common.errors import CorpusError

WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def normalize_fragment(text: str) -> str:
    """Deterministic whitespace/unicode normalization that keeps offsets usable."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item) for item in value if item]
    raise CorpusError(f"expected a string or list of strings, got {type(value).__name__}")


def assert_within(path: Path, root: Path, *, what: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CorpusError(f"{what} must stay inside {root}: {path}") from exc


def looks_like_markup(text: str) -> bool:
    return bool(
        re.search(r"<\s*(html|body|head|div|section|article|p|title|jats)", text[:4000], re.I)
    )


def detect_format(
    data: bytes,
    *,
    url: str | None = None,
    suffix: str | None = None,
    content_type: str | None = None,
) -> str:
    """Return one of ``pdf``/``xml``/``html``/``txt`` using magic bytes first."""
    if data[:5] == b"%PDF-":
        return "pdf"
    head = data[:1024].lstrip().lower()
    if head.startswith(b"<?xml"):
        return "xml"
    if b"<!doctype html" in head or b"<html" in head:
        return "html"
    if b"<jats" in data[:8192].lower():
        return "xml"
    lowered_suffix = (suffix or "").lower()
    if lowered_suffix == ".pdf":
        return "pdf"
    if lowered_suffix in {".html", ".htm"}:
        return "html"
    if lowered_suffix in {".xml", ".nxml", ".jats"}:
        return "xml"
    if lowered_suffix in {".txt", ".md", ".rst"}:
        return "txt"
    if content_type:
        content_type = content_type.lower()
        if "pdf" in content_type:
            return "pdf"
        if "html" in content_type:
            return "html"
        if "xml" in content_type:
            return "xml"
    if url:
        url_suffix = Path(urlparse(url).path).suffix.lower()
        if url_suffix and url_suffix != lowered_suffix:
            return detect_format(data, suffix=url_suffix)
    return "txt"
