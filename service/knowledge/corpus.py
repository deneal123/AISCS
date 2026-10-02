"""Draft corpus preparation module (target: ``service/knowledge/corpus.py``).

This is a *worker artifact*, not a canonical module. It is written under
``.work/pi-workers/kb-20261002/corpus/`` for review and integration by ROOT.

Design constraints encoded here:

* standard library only; ``pypdf`` is an *optional* dependency used only for PDF;
* offline by default (``download=False``); network is opt-in per call;
* at most :data:`MAX_HTTP_ATTEMPTS` attempts per registered primary URL and no
  search-engine discovery;
* no canonical file, no superproject file and no ``data/`` file is written;
* private object storage and normalized JSONL live under ``state_dir``;
* every temporary file is created inside ``state_dir``;
* identity is validated from the document title/DOI/accession against the
  canonical registry; a ``source_id`` in a filename proves nothing;
* scratch findings in ``.work`` are reported as unresolved, never bulk indexed.

The module never mutates canonical artifacts and never reads environment
variables or secrets.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from bisect import bisect_right
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

__all__ = [
    "CorpusError",
    "CHUNK_OVERLAP_TOKENS",
    "CHUNK_TARGET_TOKENS",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_TIMEOUT_S",
    "DISCOVERY_EXTENSIONS",
    "MANIFEST_ENTRY_STATUSES",
    "MAX_HTTP_ATTEMPTS",
    "TOKEN_CHARS",
    "chunk_documents",
    "discover_local_sources",
    "load_documents",
    "load_manifest",
    "normalize_candidates",
    "parse_document",
    "prepare_corpus",
    "validate_identity",
]

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

MANIFEST_ENTRY_STATUSES: tuple[str, ...] = (
    "available",
    "missing",
    "unavailable",
    "needs_ocr",
    "rejected",
    "error",
)

CHUNK_TARGET_TOKENS = 1000
CHUNK_OVERLAP_TOKENS = 100
TOKEN_CHARS = 4  # deterministic token proxy: ~4 characters per token

MAX_HTTP_ATTEMPTS = 2
DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_TIMEOUT_S = 20.0
DEFAULT_USER_AGENT = "aspa-research-corpus/0.1 (+local draft; offline by default)"

DISCOVERY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".xml",
        ".nxml",
        ".html",
        ".htm",
        ".txt",
        ".md",
        ".rst",
        ".json",
        ".jsonl",
        ".csv",
        ".tsv",
        ".bib",
        ".ris",
        ".yaml",
        ".yml",
    }
)

EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".knowledge",
        "build",
        "dist",
    }
)

# Structural registry artifacts are never source candidates.
STRUCTURAL_BASENAMES: frozenset[str] = frozenset(
    {
        "records.json",
        "aliases.json",
        "clusters.json",
        "ST.json",
        "release-manifest.json",
        "source-record.schema.json",
        "vocabularies.json",
        "applied-batches.json",
        "manifest.json",
        "package-lock.json",
        "uv.lock",
        "pyproject.toml",
    }
)

SECTION_LABELS: tuple[str, ...] = (
    "front_matter",
    "abstract",
    "introduction",
    "related_work",
    "methods",
    "results",
    "discussion",
    "limitations",
    "references",
    "acknowledgements",
    "appendix",
    "other",
    "unknown",
)

_SECTION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("abstract", ("abstract", "summary")),
    ("introduction", ("introduction", "background")),
    ("related_work", ("related work", "related works")),
    (
        "methods",
        (
            "methods",
            "method",
            "materials and methods",
            "methodology",
            "experimental",
            "experiments",
            "study design",
        ),
    ),
    ("results", ("results", "findings")),
    ("discussion", ("discussion", "conclusions", "conclusion")),
    ("limitations", ("limitations", "limitation")),
    ("references", ("references", "bibliography")),
    ("acknowledgements", ("acknowledgements", "acknowledgments", "funding")),
    ("appendix", ("appendix", "supplementary", "supplemental")),
)

_KEYWORD_TO_LABEL: dict[str, str] = {}
for _label, _keywords in _SECTION_KEYWORDS:
    for _keyword in _keywords:
        _KEYWORD_TO_LABEL[_keyword] = _label

_HEADING_KEYWORDS = "|".join(
    re.escape(keyword) for _label, keywords in _SECTION_KEYWORDS for keyword in keywords
)
_HEADING_RE = re.compile(
    r"^[ \t]{0,3}(?:[0-9]+(?:\.[0-9]+)*[.)]?[ \t]+)?"
    rf"(?P<keyword>{_HEADING_KEYWORDS})\b[^\n]{{0,80}}$",
    re.IGNORECASE | re.MULTILINE,
)

_ERROR_SIGNATURES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "error_page_detected",
        (
            "attention required! | cloudflare",
            "checking your browser before accessing",
            "just a moment...",
            "cloudflare ray id",
            "verify you are human",
            "are you a robot",
        ),
    ),
    (
        "error_page_detected",
        (
            "enable javascript and cookies to continue",
            "javascript is disabled",
            "please enable javascript",
        ),
    ),
    (
        "error_page_detected",
        (
            "403 forbidden",
            "access denied",
            "you do not have permission to access",
            "not authorized to access this page",
        ),
    ),
    (
        "error_page_detected",
        ("404 not found", "page not found", "the requested url was not found"),
    ),
    (
        "error_page_detected",
        (
            "sign in to continue",
            "log in to continue",
            "sign in to read",
            "institutional login",
            "register to continue",
            "create an account to continue",
        ),
    ),
    (
        "error_page_detected",
        (
            "subscription required",
            "subscribe to read",
            "purchase this article",
            "this content is available to subscribers",
        ),
    ),
    (
        "error_page_detected",
        ("too many requests", "rate limit exceeded", "429 too many requests"),
    ),
    (
        "error_page_detected",
        (
            "502 bad gateway",
            "503 service unavailable",
            "500 internal server error",
            "internal server error",
        ),
    ),
)

_RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

_DOI_RE = re.compile(r"\b10\.[0-9]{4,9}/[^\s\"'<>()\[\]{}]+", re.IGNORECASE)
_PMID_RE = re.compile(r"\bPMID[:\s]*([0-9]{6,9})\b", re.IGNORECASE)
_PMCID_RE = re.compile(r"\b(PMC[0-9]{6,9})\b", re.IGNORECASE)
_ARXIV_RE = re.compile(r"\barXiv[:\s]*([0-9]{4}\.[0-9]{4,5})(v[0-9]+)?", re.IGNORECASE)
_NCT_RE = re.compile(r"\b(NCT[0-9]{8})\b", re.IGNORECASE)
_GEO_RE = re.compile(r"\b(GSE[0-9]{3,})\b", re.IGNORECASE)
_SYN_RE = re.compile(r"\b(syn[0-9]{6,})\b", re.IGNORECASE)
_PRJ_RE = re.compile(r"\b(PRJ[END][A-Z][0-9]{4,})\b", re.IGNORECASE)

_TITLE_STOPWORDS = frozenset(
    {
        "abstract",
        "summary",
        "introduction",
        "methods",
        "results",
        "discussion",
        "references",
        "acknowledgements",
        "acknowledgments",
        "article",
        "research article",
        "original article",
        "review",
        "preprint",
        "doi",
        "journal",
        "volume",
        "downloaded from",
        "accepted manuscript",
        "supplementary material",
    }
)

_PARAGRAPH_RE = re.compile(r"[^\n]+(?:\n(?![ \t]*\n)[^\n]*)*")
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]*(?:\s+|$)")
_WHITESPACE_RE = re.compile(r"\s+")

# Test seam: replaceable callable with the signature of ``_http_fetch``.
HTTP_FETCHER = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


class CorpusError(RuntimeError):
    """Invalid corpus request: bad candidate mapping or unsafe state directory."""


class DiscoveryError(CorpusError):
    """Conservative discovery refused to classify an entry or index it."""


class IdentifierMismatch(CorpusError):
    """A document identity did not match the declared canonical identity."""


class DownloadRefused(CorpusError):
    """A download was requested but policy forbids or blocks it."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _norm_fragment(text: str) -> str:
    """Deterministic whitespace/unicode normalization that keeps offsets usable."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def normalize_text(text: str) -> str:
    """Public alias of :func:`_norm_fragment`; safe for arbitrary input."""
    return _norm_fragment(text)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item) for item in value if item]
    raise CorpusError(f"expected a string or list of strings, got {type(value).__name__}")


def _assert_within(path: Path, root: Path, *, what: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CorpusError(f"{what} must stay inside {root}: {path}") from exc


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via a temporary sibling inside ``state_dir`` (never a root scratch file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _looks_like_markup(text: str) -> bool:
    return bool(
        re.search(r"<\s*(html|body|head|div|section|article|p|title|jats)", text[:4000], re.I)
    )


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + TOKEN_CHARS - 1) // TOKEN_CHARS)


def _page_at(page_starts: Sequence[int], offset: int) -> int | None:
    if not page_starts:
        return None
    return bisect_right(page_starts, offset)


# ---------------------------------------------------------------------------
# format detection, decoding, parsing
# ---------------------------------------------------------------------------


def decode_bytes(data: bytes) -> tuple[str, str]:
    """Decode common encodings deterministically, without touching the environment."""
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace"), "latin-1"


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


class _HTMLExtractor(HTMLParser):
    """Collect text plus heading offsets from HTML without external dependencies."""

    _SKIP = frozenset({"script", "style", "noscript", "template"})
    _BLOCK = frozenset(
        {
            "p",
            "div",
            "br",
            "li",
            "tr",
            "td",
            "th",
            "section",
            "article",
            "header",
            "footer",
            "table",
            "ul",
            "ol",
            "blockquote",
            "pre",
            "figure",
            "figcaption",
            "dd",
            "dt",
            "main",
            "nav",
            "aside",
        }
    )
    _HEADING = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "title"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._length = 0
        self._skip = 0
        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []
        self._heading_offset: int | None = None
        self.headings: list[tuple[int, str, str]] = []

    def _append(self, text: str) -> None:
        if not text:
            return
        self._parts.append(text)
        self._length += len(text)

    def _close_heading(self) -> None:
        if self._heading_tag is None:
            return
        raw = " ".join(" ".join(self._heading_parts).split())
        if raw:
            label = "front_matter" if self._heading_tag == "title" else classify_heading(raw)
            self.headings.append((self._heading_offset or 0, label, raw))
        self._heading_tag = None
        self._heading_parts = []
        self._heading_offset = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip += 1
            return
        if tag in self._HEADING:
            self._close_heading()
            self._heading_tag = tag
            self._heading_parts = []
            self._heading_offset = self._length
            self._append("\n")
            return
        if tag in self._BLOCK:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag in self._HEADING:
            self._close_heading()
            self._append("\n")
            return
        if tag in self._BLOCK:
            self._append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._heading_tag is not None and self._heading_offset is None:
            self._heading_offset = self._length
        if self._heading_tag is not None:
            self._heading_parts.append(data)
        self._append(data)

    def text(self) -> str:
        self._close_heading()
        return "".join(self._parts)


def _markup_text(markup: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Convert markup to normalized text while keeping heading offsets."""
    stripped = re.sub(r"(?is)<(script|style|noscript|template)\b[^>]*>.*?</\1\s*>", " ", markup)
    extractor = _HTMLExtractor()
    try:
        extractor.feed(stripped)
        extractor.close()
    except Exception:  # noqa: BLE001 - malformed markup must not abort the corpus
        return _norm_fragment(re.sub(r"(?s)<[^>]+>", " ", stripped)), []
    text = _norm_fragment(extractor.text())
    headings = _valid_headings(text, extractor.headings)
    if not headings:
        headings = _keyword_headings(text)
    return text, headings


def _valid_headings(
    text: str, headings: Iterable[tuple[int, str, str]]
) -> list[tuple[int, str, str]]:
    cleaned: list[tuple[int, str, str]] = []
    for offset, label, raw in sorted(headings, key=lambda item: item[0]):
        offset = max(0, min(offset, len(text)))
        if label not in SECTION_LABELS:
            label = "other"
        if cleaned and cleaned[-1][0] == offset:
            continue
        cleaned.append((offset, label, raw))
    return cleaned


def classify_heading(raw: str) -> str:
    """Map a heading line to a schema-style section label."""
    lowered = raw.casefold().strip(" .:-\u2014")
    for label, keywords in _SECTION_KEYWORDS:
        for keyword in keywords:
            if (
                lowered == keyword
                or lowered.startswith(keyword + " ")
                or lowered.startswith(keyword + ":")
            ):
                return label
    if re.match(r"^[0-9]+(?:\.[0-9]+)*[.)]?\s", raw):
        return "other"
    return "other"


def _keyword_headings(text: str) -> list[tuple[int, str, str]]:
    headings: list[tuple[int, str, str]] = []
    for match in _HEADING_RE.finditer(text):
        raw = match.group(0).strip()
        label = _KEYWORD_TO_LABEL.get(match.group("keyword").casefold(), "other")
        headings.append((match.start(), label, raw))
    return _valid_headings(text, headings)


def _pdf_pages(data: bytes) -> tuple[list[str] | None, str | None]:
    """Return per-page text, or ``(None, reason)`` when PDF text is unavailable."""
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError:
        return None, "pypdf_not_installed"
    import io

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - third-party parser boundary
        return None, f"pdf_parse_failed:{type(exc).__name__}"
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001 - third-party parser boundary
            return None, "pdf_encrypted"
    pages: list[str] = []
    for page in reader.pages:
        try:
            raw = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - third-party parser boundary
            raw = ""
        pages.append(_norm_fragment(raw))
    return pages, None


def parse_document(
    payload: bytes | str,
    *,
    url: str | None = None,
    suffix: str | None = None,
    content_type: str | None = None,
    http_status: int | None = None,
) -> dict[str, Any]:
    """Parse one payload into normalized text, sections and quality flags.

    The returned dict preserves ``char_start``/``char_end`` offsets into ``text``,
    a page for every section when the format is paginated, and the detected
    error/login-page reason (if any).
    """
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    fmt = detect_format(data, url=url, suffix=suffix, content_type=content_type)
    result: dict[str, Any] = {
        "format": fmt,
        "text": "",
        "page_starts": None,
        "headings": [],
        "title": None,
        "needs_ocr": False,
        "error": None,
        "reason": None,
        "error_page": None,
    }
    if fmt == "pdf":
        pages, pdf_error = _pdf_pages(data)
        if pdf_error:
            if pdf_error == "pypdf_not_installed":
                result.update(error=pdf_error, reason="pdf_text_extraction_unavailable")
            elif pdf_error == "pdf_encrypted":
                result.update(error=pdf_error, reason="pdf_encrypted")
            else:
                result.update(error=pdf_error, reason=pdf_error)
            result["needs_ocr"] = True
            return result
        assert pages is not None
        text = "\n\n".join(pages)
        page_starts: list[int] = []
        offset = 0
        for page in pages:
            page_starts.append(offset)
            offset += len(page) + 2
        result["page_starts"] = page_starts
        result["text"] = text
        result["headings"] = _keyword_headings(text)
        result["title"] = _extract_title(text, None)
        if not text.strip():
            result.update(needs_ocr=True, reason="no_extractable_text")
        return result

    decoded, _encoding = decode_bytes(data)
    if fmt in {"html", "xml"} or _looks_like_markup(decoded):
        if fmt == "txt" and _looks_like_markup(decoded):
            fmt = "html"
            result["format"] = "html"
        text, headings = _markup_text(decoded)
    else:
        text = _norm_fragment(decoded)
        headings = _keyword_headings(text)
    result["text"] = text
    result["headings"] = headings
    result["title"] = _extract_title(text, _heading_title(headings))
    if not text.strip():
        result.update(needs_ocr=True, reason="empty_document")
        return result
    error_reason = detect_error_page(text, url=url, http_status=http_status)
    if error_reason:
        result["error_page"] = error_reason
    return result


def _heading_title(headings: Sequence[tuple[int, str, str]]) -> str | None:
    for _offset, label, raw in headings:
        if label in {"front_matter", "other"} and raw:
            return raw
    return None


def _extract_title(text: str, markup_title: str | None) -> str | None:
    if markup_title:
        cleaned = markup_title.strip()
        if cleaned:
            return cleaned[:400]
    for line in text.splitlines()[:40]:
        candidate = line.strip()
        if not 6 <= len(candidate) <= 300:
            continue
        if candidate.casefold().strip(" .:-\u2014") in _TITLE_STOPWORDS:
            continue
        if _DOI_RE.search(candidate) and len(candidate) < 40:
            continue
        return candidate
    return None


def detect_error_page(
    text: str, *, url: str | None = None, http_status: int | None = None
) -> str | None:
    """Return a reason when the payload looks like an error/login/interstitial page.

    Detection is deliberately conservative: a strong HTTP status always counts,
    otherwise the signature must appear in the head of a short document.
    """
    if http_status is not None and (http_status in {401, 403, 404, 429} or http_status >= 500):
        return "error_page_detected"
    if len(text) > 8000:
        return None
    head = text[:2500].casefold()
    for reason, signatures in _ERROR_SIGNATURES:
        if any(signature in head for signature in signatures):
            words = _WHITESPACE_RE.split(text.strip())
            if len(words) <= 400:
                return reason
    if url and not text.strip():
        return "error_page_detected"
    return None


# ---------------------------------------------------------------------------
# identifiers and identity validation
# ---------------------------------------------------------------------------


def _normalize_title(value: str | None) -> str | None:
    if not value:
        return None
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = re.sub(r"[^0-9a-z\u0400-\u04ff]+", " ", folded)
    folded = _WHITESPACE_RE.sub(" ", folded).strip()
    return folded or None


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().rstrip(".,;)]}").casefold()
    cleaned = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", cleaned)
    return cleaned or None


def extract_identifiers(text: str) -> dict[str, Any]:
    """Extract DOI/accession candidates from document text (never from filenames)."""
    head = text[:200000]
    dois = sorted({match.group(0).rstrip(".,;)]}").casefold() for match in _DOI_RE.finditer(head)})
    pmids = sorted({match.group(1) for match in _PMID_RE.finditer(head)})
    pmcids = sorted({match.group(1).upper() for match in _PMCID_RE.finditer(head)})
    arxiv = sorted(
        {f"{match.group(1)}{match.group(2) or ''}" for match in _ARXIV_RE.finditer(head)}
    )
    nct = sorted({match.group(1).upper() for match in _NCT_RE.finditer(head)})
    geo = sorted({match.group(1).upper() for match in _GEO_RE.finditer(head)})
    synapse = sorted({match.group(1) for match in _SYN_RE.finditer(head)})
    bioproject = sorted({match.group(1).upper() for match in _PRJ_RE.finditer(head)})
    return {
        "doi": dois,
        "pmid": pmids,
        "pmcid": pmcids,
        "arxiv_id": arxiv,
        "nct": nct,
        "geo": geo,
        "synapse": synapse,
        "bioproject": bioproject,
    }


def validate_identity(
    extracted: Mapping[str, Any],
    expected: Mapping[str, Any] | None,
    *,
    title: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Validate document title/DOI/accession against a canonical identity.

    ``extracted`` is the output of :func:`extract_identifiers`; ``expected`` maps
    canonical fields (``title``, ``doi``, ``pmid``, ``arxiv_id``, ``dataset_id``,
    ``patent_id``, ``exact_url``). A filename is never consulted.
    """
    evidence: dict[str, Any] = {"matched": [], "checked": [], "title": title}
    if not expected:
        evidence["reason"] = "no_canonical_identity"
        return False, evidence

    norm_doc_title = _normalize_title(title)
    norm_expected_title = _normalize_title(expected.get("title"))
    if norm_doc_title and norm_expected_title:
        evidence["checked"].append("title")
        if norm_doc_title == norm_expected_title:
            evidence["matched"].append("title")
    expected_doi = _normalize_doi(expected.get("doi"))
    doc_dois = {_normalize_doi(item) for item in extracted.get("doi", [])}
    doc_dois.discard(None)
    if expected_doi:
        evidence["checked"].append("doi")
        if expected_doi in doc_dois:
            evidence["matched"].append("doi")

    accession_pairs = (
        ("pmid", extracted.get("pmid", [])),
        ("pmcid", extracted.get("pmcid", [])),
        ("arxiv_id", extracted.get("arxiv_id", [])),
        ("nct", extracted.get("nct", [])),
        ("geo", extracted.get("geo", [])),
        ("synapse", extracted.get("synapse", [])),
        ("bioproject", extracted.get("bioproject", [])),
    )
    doc_accessions = {str(item).upper() for _kind, items in accession_pairs for item in items}
    for field in ("pmid", "arxiv_id", "dataset_id", "patent_id"):
        canonical_value = expected.get(field)
        if not canonical_value:
            continue
        evidence["checked"].append(field)
        normalized = str(canonical_value).upper()
        if normalized in doc_accessions or any(
            normalized in str(item).upper() for item in doc_accessions
        ):
            evidence["matched"].append(field)

    evidence["extracted"] = {
        "doi": sorted(doc_dois),
        "accessions": sorted(doc_accessions),
    }
    matched = bool(evidence["matched"])
    if not evidence["checked"]:
        evidence["reason"] = "canonical_identity_has_no_comparable_fields"
        return False, evidence
    if not matched:
        evidence["reason"] = "identity_not_matched"
    return matched, evidence


# ---------------------------------------------------------------------------
# canonical registry (read-only)
# ---------------------------------------------------------------------------


def _records_path(root: Path) -> Path | None:
    for candidate in (root / "data" / "records.json", root / "records.json"):
        if candidate.is_file():
            return candidate
    return None


def _identity_from_payload(payload: Any) -> dict[str, dict[str, Any]]:
    sources = payload.get("sources") if isinstance(payload, Mapping) else None
    if not isinstance(sources, list):
        return {}
    identities: dict[str, dict[str, Any]] = {}
    for record in sources:
        if not isinstance(record, Mapping):
            continue
        source_id = record.get("id")
        if not isinstance(source_id, str) or not re.fullmatch(r"S[0-9]{3,}", source_id):
            continue
        identifiers = record.get("identifiers") or {}
        if not isinstance(identifiers, Mapping):
            identifiers = {}
        identities[source_id] = {
            "title": record.get("название") or record.get("title"),
            "doi": identifiers.get("doi"),
            "pmid": identifiers.get("pmid"),
            "arxiv_id": identifiers.get("arxiv_id"),
            "patent_id": identifiers.get("patent_id"),
            "dataset_id": identifiers.get("dataset_id"),
            "exact_url": identifiers.get("exact_url"),
        }
    return identities


def _mapping_with_sources(repository: Any) -> Mapping[str, Any] | None:
    if isinstance(repository, Mapping) and "sources" in repository:
        return repository
    return None


def _repository_view(repository: Any) -> tuple[Path | None, dict[str, dict[str, Any]]]:
    """Accept a project root, a data directory, a registry mapping or a repository object.

    Returns ``(project_root, identities)``. ``project_root`` is ``None`` only when
    the caller supplied a bare registry mapping without any filesystem anchor.
    """
    mapping = _mapping_with_sources(repository)
    if mapping is not None:
        return None, _identity_from_payload(mapping)
    if hasattr(repository, "bundle") and callable(repository.bundle):
        records: Mapping[str, Any] = {}
        try:
            bundle = repository.bundle()
            records = getattr(bundle, "records", None) or {}
        except Exception:  # noqa: BLE001 - repository boundary; treat as unavailable
            records = {}
        data_dir = getattr(repository, "data_dir", None)
        root = Path(data_dir).resolve().parent if data_dir else None
        return root, _identity_from_payload(records)
    sources_attr = getattr(repository, "sources", None)
    if sources_attr is not None and not isinstance(repository, (str, Path)):
        return None, _identity_from_payload({"sources": list(sources_attr)})

    path = Path(repository)
    if path.is_file():
        parent = path.parent
        root = parent.parent if parent.name == "data" else parent
        records_path: Path | None = path
    elif path.is_dir():
        records_path = _records_path(path)
        if records_path is None:
            return path, {}
        root = (
            path
            if records_path == path / "data" / "records.json"
            else (path.parent if path.name == "data" else path)
        )
    else:
        raise CorpusError(f"repository does not exist: {path}")
    if records_path is None:
        return root, {}
    try:
        payload = json.loads(records_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return root, {}
    return root, _identity_from_payload(payload)


def load_canonical_identity(repository: Any) -> dict[str, dict[str, Any]]:
    """Read the canonical registry read-only and return ``source_id -> identity``.

    ``repository`` may be the project root (``data/records.json`` is preferred,
    with a bare ``records.json`` fallback), the ``data`` directory itself, a
    ``ResearchRepository``-like object exposing ``bundle()``/``data_dir``, or a
    mapping carrying ``sources``. A missing or malformed registry yields ``{}``
    and the caller must then treat every candidate as identity-unverified.
    """
    return _repository_view(repository)[1]


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------


def _new_candidate(
    *,
    source_id: str | None,
    provisional_id: str,
    paths: Sequence[str],
    primary_urls: Sequence[str],
    identity_verified_claim: bool,
    expected: Mapping[str, Any] | None = None,
    source_class: str = "candidate",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "provisional_id": provisional_id,
        "paths": list(dict.fromkeys(paths)),
        "primary_urls": list(dict.fromkeys(primary_urls)),
        "identity_verified_claim": bool(identity_verified_claim),
        "expected": dict(expected) if expected else None,
        "source_class": source_class,
    }


def normalize_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate and group explicit ``{source_id,path,primary_url,identity_verified}``.

    Multiple candidates for one ``source_id`` are merged; ``identity_verified`` is
    only an input claim and is re-checked later against document content.
    """
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise CorpusError("candidates must be a sequence of mappings")
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in candidates:
        if not isinstance(raw, Mapping):
            raise CorpusError("every candidate must be a mapping")
        source_id = raw.get("source_id")
        if source_id is not None:
            source_id = str(source_id)
            if not re.fullmatch(r"S[0-9]{3,}", source_id):
                raise CorpusError(f"invalid source_id: {source_id!r}")
        paths = _as_list(raw.get("path")) + _as_list(raw.get("paths"))
        urls = _as_list(raw.get("primary_url")) + _as_list(raw.get("primary_urls"))
        if not paths and not urls:
            raise CorpusError(f"candidate {source_id or '<discovery>'} has no path or primary_url")
        expected = raw.get("expected")
        if expected is not None and not isinstance(expected, Mapping):
            raise CorpusError("candidate 'expected' must be a mapping when present")
        key = source_id if source_id is not None else f"local:{paths[0]}"
        if key not in grouped:
            order.append(key)
            grouped[key] = _new_candidate(
                source_id=source_id,
                provisional_id=key,
                paths=paths,
                primary_urls=urls,
                identity_verified_claim=bool(raw.get("identity_verified", False)),
                expected=expected,
            )
        else:
            merged = grouped[key]
            merged["paths"] = list(dict.fromkeys([*merged["paths"], *paths]))
            merged["primary_urls"] = list(dict.fromkeys([*merged["primary_urls"], *urls]))
            merged["identity_verified_claim"] = merged["identity_verified_claim"] or bool(
                raw.get("identity_verified", False)
            )
            if expected and not merged["expected"]:
                merged["expected"] = dict(expected)
    return [grouped[key] for key in order]


DEFAULT_MAX_SCRATCH_FILES = 5000


def _classify_relative(parts: Sequence[str]) -> str:
    if parts and parts[0] == ".work":
        return "scratch"
    if parts and parts[0] in {
        "data",
        "tests",
        "docs",
        "migrations",
        "scripts",
        "service",
        "knowledge",
        "publications",
        "presentation",
        "text",
        "agents",
        "backend",
        "frontend",
        "infra",
        "docker",
    }:
        return "repository_artifact"
    return "candidate"


def _scan_local_sources(
    root: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_scratch_files: int = DEFAULT_MAX_SCRATCH_FILES,
) -> tuple[list[dict[str, Any]], bool]:
    """Classify local files without ever parsing or indexing them.

    ``.work`` is walked last so scratch volume can never hide registry artifacts
    or root-level candidates. Scratch entries beyond ``max_scratch_files`` are
    dropped and the truncation is reported explicitly.
    """
    root = root.resolve()
    found: list[dict[str, Any]] = []
    truncated = False
    scratch_count = 0

    def collect(path: Path, *, is_scratch: bool) -> bool:
        nonlocal truncated, scratch_count
        if path.name in STRUCTURAL_BASENAMES:
            return True
        if path.suffix.lower() not in DISCOVERY_EXTENSIONS:
            return True
        try:
            stat = path.stat()
        except OSError:
            return True
        if stat.st_size > max_bytes:
            return True
        try:
            relative = path.relative_to(root)
        except ValueError:
            return True
        if is_scratch and scratch_count >= max_scratch_files:
            truncated = True
            return False
        if is_scratch:
            scratch_count += 1
        rel_posix = relative.as_posix()
        found.append(
            _new_candidate(
                source_id=None,
                provisional_id=f"local:{rel_posix}",
                paths=[rel_posix],
                primary_urls=[],
                identity_verified_claim=False,
                source_class="scratch" if is_scratch else _classify_relative(relative.parts),
            )
            | {
                "relative_path": rel_posix,
                "bytes": stat.st_size,
                "extension": path.suffix.lower(),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
        return True

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if name not in EXCLUDED_DIR_NAMES and name != ".work"
        )
        current = Path(dirpath)
        for filename in sorted(filenames):
            collect(current / filename, is_scratch=False)

    scratch_root = root / ".work"
    if scratch_root.is_dir():
        stop = False
        for dirpath, dirnames, filenames in os.walk(scratch_root):
            if stop:
                break
            dirnames[:] = sorted(name for name in dirnames if name not in EXCLUDED_DIR_NAMES)
            current = Path(dirpath)
            for filename in sorted(filenames):
                if not collect(current / filename, is_scratch=True):
                    stop = True
                    break
    return found, truncated


def discover_local_sources(
    repository: Path | str, *, max_bytes: int = DEFAULT_MAX_BYTES
) -> list[dict[str, Any]]:
    """Conservatively classify local files; never index them.

    Files below ``.work`` are reported as scratch. Registry-style files and
    repository tooling are reported as artifacts. Only unclassified document-like
    files become discovery candidates, and they still require identity validation
    before they can ever be indexed.
    """
    scanned, _truncated = _scan_local_sources(repository, max_bytes=max_bytes)
    return scanned


# ---------------------------------------------------------------------------
# download (offline by default, no search)
# ---------------------------------------------------------------------------


def _http_fetch(
    url: str,
    *,
    max_attempts: int = MAX_HTTP_ATTEMPTS,
    timeout: float = DEFAULT_TIMEOUT_S,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Fetch one registered URL with a hard attempt/byte/time limit.

    Retries only transient failures. No search endpoint is ever contacted and no
    new URL is derived from a response.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise DownloadRefused(f"refusing non-http(s) URL: {url}")
    if max_attempts < 1:
        raise DownloadRefused("max_attempts must be positive")
    attempts = 0
    last_error: str | None = None
    last_status: int | None = None
    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*"})
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit URL
                status = int(getattr(response, "status", 200))
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    return {
                        "ok": False,
                        "attempts": attempts,
                        "status": status,
                        "final_url": response.geturl(),
                        "content_type": response.headers.get("Content-Type"),
                        "body": None,
                        "error": "response_too_large",
                    }
                return {
                    "ok": True,
                    "attempts": attempts,
                    "status": status,
                    "final_url": response.geturl(),
                    "content_type": response.headers.get("Content-Type"),
                    "body": body,
                    "error": None,
                }
        except HTTPError as exc:
            last_status = int(exc.code)
            last_error = f"http_{exc.code}"
            if exc.code not in _RETRYABLE_HTTP_STATUS or attempt >= max_attempts:
                break
        except URLError as exc:
            last_error = f"url_error:{type(exc.reason).__name__}"
            if attempt >= max_attempts:
                break
        except TimeoutError:
            last_error = "timeout"
            if attempt >= max_attempts:
                break
    return {
        "ok": False,
        "attempts": attempts,
        "status": last_status,
        "final_url": url,
        "content_type": None,
        "body": None,
        "error": last_error or "fetch_failed",
    }


def _fetch(url: str, **kwargs: Any) -> dict[str, Any]:
    fetcher = HTTP_FETCHER or _http_fetch
    return fetcher(url, **kwargs)


# ---------------------------------------------------------------------------
# chunking
# ---------------------------------------------------------------------------


def _paragraph_units(text: str) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    for match in _PARAGRAPH_RE.finditer(text):
        start, end = _trim(text, match.start(), match.end())
        if start < end:
            units.append((start, end))
    return units


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _split_oversized(text: str, start: int, end: int, target_tokens: int) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    for match in _SENTENCE_RE.finditer(text, start, end):
        s, e = _trim(text, match.start(), match.end())
        if s < e:
            units.append((s, e))
    if units and _estimate_tokens(text[start:end]) > target_tokens:
        return units
    return [(start, end)]


def _pack_units(
    text: str, units: Sequence[tuple[int, int]], target_tokens: int, overlap_tokens: int
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    count = len(units)
    index = 0
    while index < count:
        cursor = index
        tokens = 0
        while cursor < count:
            unit_tokens = _estimate_tokens(text[units[cursor][0] : units[cursor][1]])
            if tokens > 0 and tokens + unit_tokens > target_tokens:
                break
            tokens += unit_tokens
            cursor += 1
            if tokens >= target_tokens:
                break
        spans.append((units[index][0], units[cursor - 1][1]))
        if cursor >= count:
            break
        back = cursor
        overlap = 0
        while back - 1 > index:
            unit_tokens = _estimate_tokens(text[units[back - 1][0] : units[back - 1][1]])
            if overlap + unit_tokens > overlap_tokens:
                break
            overlap += unit_tokens
            back -= 1
        index = cursor if back <= index else back
    return spans


def _overlap_labels(sections: Sequence[Mapping[str, Any]], start: int, end: int) -> list[str]:
    labels: list[str] = []
    for section in sections:
        section_start = int(section.get("char_start", 0))
        section_end = int(section.get("char_end", 0))
        if section_end <= start or section_start >= end:
            continue
        label = str(section.get("label", "unknown"))
        if label not in labels:
            labels.append(label)
    return labels or ["unknown"]


def chunk_documents(
    documents: Sequence[Mapping[str, Any]],
    *,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
    token_chars: int = TOKEN_CHARS,
) -> list[dict[str, Any]]:
    """Chunk normalized documents on paragraph boundaries with fixed coordinates.

    Every chunk carries exact ``char_start``/``char_end`` offsets into the parent
    ``text``, page coordinates when available, section labels and two stable
    SHA-256 hashes. Repeated calls over the same documents are byte-identical.
    """
    if target_tokens < 1:
        raise CorpusError("target_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise CorpusError("overlap_tokens must be >= 0 and < target_tokens")
    del token_chars  # retained for API compatibility with callers tuning the proxy
    chunks: list[dict[str, Any]] = []
    for document in documents:
        text = str(document.get("text", ""))
        source_id = str(document.get("source_id", "unknown"))
        doc_sha = str(document.get("sha256", ""))
        page_starts = document.get("page_starts") or []
        sections = list(document.get("sections") or [])
        units: list[tuple[int, int]] = []
        for start, end in _paragraph_units(text):
            if _estimate_tokens(text[start:end]) > target_tokens:
                units.extend(_split_oversized(text, start, end, target_tokens))
            else:
                units.append((start, end))
        if not units and text:
            units = _split_oversized(text, 0, len(text), target_tokens)
        spans = _pack_units(text, units, target_tokens, overlap_tokens)
        for index, (start, end) in enumerate(spans):
            body = text[start:end]
            text_hash = _sha256_text(body)
            chunk_id = f"{source_id}::{doc_sha[:12]}::{index:05d}::{text_hash[:12]}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "source_id": source_id,
                    "doc_sha256": doc_sha,
                    "document_version": document.get("version"),
                    "chunk_index": index,
                    "chunk_count": len(spans),
                    "char_start": start,
                    "char_end": end,
                    "page_start": _page_at(page_starts, start),
                    "page_end": _page_at(page_starts, max(start, end - 1)),
                    "section_labels": _overlap_labels(sections, start, end),
                    "token_estimate": _estimate_tokens(body),
                    "text": body,
                    "text_sha256": text_hash,
                    "chunk_sha256": _sha256_text(f"{chunk_id}\0{body}"),
                }
            )
    return chunks


# ---------------------------------------------------------------------------
# section construction
# ---------------------------------------------------------------------------


def _build_sections(
    text: str,
    headings: Sequence[tuple[int, str, str]],
    page_starts: Sequence[int] | None,
) -> list[dict[str, Any]]:
    ordered = _valid_headings(text, headings)
    if not ordered or ordered[0][0] != 0:
        ordered = [(0, "front_matter", "front_matter"), *ordered]
    merged: list[tuple[int, str]] = []
    for offset, label, _raw in ordered:
        if merged and merged[-1][1] == label:
            continue
        merged.append((offset, label))
    sections: list[dict[str, Any]] = []
    for position, (offset, label) in enumerate(merged):
        char_end = merged[position + 1][0] if position + 1 < len(merged) else len(text)
        if char_end < offset:
            char_end = offset
        sections.append(
            {
                "label": label,
                "page": _page_at(page_starts, offset) if page_starts else None,
                "char_start": offset,
                "char_end": char_end,
            }
        )
    return sections


# ---------------------------------------------------------------------------
# prepare_corpus
# ---------------------------------------------------------------------------


def prepare_corpus(
    repository: Any,
    state_dir: Path,
    *,
    candidates: list[dict] | None = None,
    download: bool = False,
) -> dict:
    """Build a private corpus store plus an owner-reviewed manifest.

    Parameters
    ----------
    repository:
        Project root (``R:\\Aspa\\research``), its ``data`` directory, a
        ``ResearchRepository``-like object exposing ``bundle()``/``data_dir``, or a
        mapping carrying ``sources`` (that last form has no filesystem anchor and
        is only usable with :func:`load_canonical_identity`). Only ``records.json``
        is ever read, and only to obtain canonical identities.
    state_dir:
        Private state directory. It is forced to resolve inside ``repository``
        (e.g. ``.knowledge``). Objects go to ``state_dir/corpus/objects/<sha256>``
        and normalized documents to ``state_dir/corpus/documents.jsonl``.
    candidates:
        Explicit ``{source_id, path, primary_url, identity_verified}`` mappings.
        ``None`` triggers conservative local discovery, which reports scratch and
        repository artifacts as unresolved and indexes nothing without identity.
    download:
        Opt-in network use for registered primary URLs. Offline by default, at
        most :data:`MAX_HTTP_ATTEMPTS` attempts, no new source searches.

    Returns
    -------
    dict
        Summary with counts, the working manifest, the discovery report and the
        paths of every written artifact. The *tracked* manifest remains owned by
        ROOT and is written separately.
    """
    resolved_root, canonical = _repository_view(repository)
    if resolved_root is None:
        raise CorpusError(
            "repository must be a project root, data directory or repository object; "
            "a bare registry mapping provides no filesystem anchor for state_dir"
        )
    repo = resolved_root
    if not repo.is_dir():
        raise CorpusError(f"repository is not a directory: {repo}")
    requested_state = Path(state_dir)
    if not requested_state.is_absolute():
        requested_state = repo / requested_state
    private = requested_state.resolve()
    _assert_within(private, repo, what="state_dir")

    corpus_dir = private / "corpus"
    objects_dir = corpus_dir / "objects"
    documents_path = corpus_dir / "documents.jsonl"
    manifest_path = corpus_dir / "manifest.json"
    report_path = corpus_dir / "scratch-discovery.json"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    objects_dir.mkdir(parents=True, exist_ok=True)

    generated_at = _now_iso()

    discovery_report: dict[str, Any]
    if candidates is None:
        scanned, truncated = _scan_local_sources(repo)
        normalized = [item for item in scanned if item["source_class"] == "candidate"]
        discovery_report = _build_discovery_report(scanned, truncated, generated_at, repo, private)
    else:
        normalized = normalize_candidates(candidates)
        discovery_report = _empty_discovery_report(generated_at, repo, private)

    by_source: dict[str, dict[str, Any]] = {
        item["source_id"]: item for item in normalized if item["source_id"]
    }
    discovery_candidates = [item for item in normalized if not item["source_id"]]

    entries: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    entry_by_source: dict[str, dict[str, Any]] = {}
    previous_documents = {}
    previous_entries = {}
    if documents_path.exists() and manifest_path.exists():
        previous_documents = {
            d["source_id"]: d
            for d in (
                json.loads(line)
                for line in documents_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        }
        previous_entries = {
            e["source_id"]: e
            for e in json.loads(manifest_path.read_text(encoding="utf-8"))["entries"]
        }

    ordered_ids = list(canonical.keys())
    if set(by_source) - set(canonical):
        raise CorpusError("candidate references a source outside the canonical registry")

    for source_id in ordered_ids:
        candidate = by_source.get(source_id)
        previous = previous_documents.get(source_id)
        identity_hash = _sha256_text(_json_dumps(canonical[source_id]))
        old_entry = previous_entries.get(source_id)
        if (
            candidate is None
            and not download
            and old_entry
            and old_entry.get("canonical_identity_sha256") == identity_hash
            and old_entry["status"] != "available"
        ):
            entries.append(old_entry)
            entry_by_source[source_id] = old_entry
            continue
        if previous and previous.get("canonical_identity_sha256") == identity_hash:
            raw = objects_dir / previous["sha256"]
            if (
                raw.exists()
                and _sha256_bytes(raw.read_bytes()) == previous["sha256"]
                and _sha256_text(previous["text"]) == previous["text_sha256"]
            ):
                entries.append(previous_entries[source_id])
                entry_by_source[source_id] = entries[-1]
                documents.append(previous)
                continue
        entry, document = _resolve_source(
            source_id=source_id,
            candidate=candidate,
            expected=_expected_identity(canonical.get(source_id), candidate),
            repo=repo,
            objects_dir=objects_dir,
            generated_at=generated_at,
            download=download,
        )
        entries.append(entry)
        entry["canonical_identity_sha256"] = identity_hash
        entry_by_source[source_id] = entry
        if document is not None:
            document["canonical_identity_sha256"] = identity_hash
            document["primary_url"] = canonical[source_id].get("exact_url")
            documents.append(document)

    discovery_report["unregistered_candidates"] = [
        _rejected_discovery_entry(candidate, generated_at) for candidate in discovery_candidates
    ]

    for document in documents:
        chunk_count = len(chunk_documents([document]))
        entry_by_source[document["source_id"]]["chunk_count"] = chunk_count

    lines = "".join(_json_dumps(document) + "\n" for document in documents)
    _atomic_write_text(documents_path, lines)

    manifest = {
        "generated_at": generated_at,
        "repository": str(repo),
        "state_dir": str(private),
        "offline": not download,
        "entries": entries,
        "discovery": [item for item in normalized if not item["source_id"]],
    }
    manifest_bytes = (_json_dumps(manifest) + "\n").encode("utf-8")
    _atomic_write_bytes(manifest_path, manifest_bytes)
    _atomic_write_text(report_path, _json_dumps(discovery_report) + "\n")

    counts = {status: 0 for status in MANIFEST_ENTRY_STATUSES}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1

    return {
        "repository": str(repo),
        "state_dir": str(private),
        "generated_at": generated_at,
        "download": download,
        "counts": {
            "canonical_sources": len(canonical),
            "manifest_entries": len(entries),
            "documents": len(documents),
            "scratch_candidates": len(discovery_report.get("scratch_candidates", [])),
            **counts,
        },
        "manifest": manifest,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "manifest_path": str(manifest_path),
        "documents_path": str(documents_path),
        "objects_dir": str(objects_dir),
        "scratch_report_path": str(report_path),
        "unresolved": discovery_report.get("unresolved", []),
    }


def portable_manifest(result: dict, project: Path) -> dict:
    """Public registry contains portable locators; private runtime details stay private."""
    manifest = json.loads(json.dumps(result["manifest"]))
    manifest["repository"] = "."
    manifest["state_dir"] = ".knowledge"
    docs = [
        json.loads(line)
        for line in Path(result["documents_path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {doc["source_id"]: doc for doc in docs}
    for entry in manifest["entries"]:
        paths = []
        for raw in entry["paths"]:
            path = Path(raw)
            paths.append(
                path.relative_to(project).as_posix() if path.is_absolute() else path.as_posix()
            )
        entry["paths"] = paths
        entry["completeness"] = by_id.get(entry["source_id"], {}).get("completeness", "unavailable")
    return manifest


def _expected_identity(
    canonical: Mapping[str, Any] | None, candidate: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    if canonical:
        return dict(canonical)
    return None


def _new_entry(source_id: str, generated_at: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "status": "missing",
        "reason": "no_candidate_locator",
        "primary_urls": [],
        "paths": [],
        "sha256": None,
        "version": None,
        "bytes": None,
        "retrieved_at": None,
        "checked_at": generated_at,
        "page_count": None,
        "sections": [],
        "chunk_count": 0,
        "identity_verified": False,
        "identity_evidence": {},
        "content_type": None,
        "format": None,
        "http_status": None,
        "error": None,
        "warnings": [],
    }


def _resolve_source(
    *,
    source_id: str,
    candidate: Mapping[str, Any] | None,
    expected: Mapping[str, Any] | None,
    repo: Path,
    objects_dir: Path,
    generated_at: str,
    download: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    entry = _new_entry(source_id, generated_at)
    canonical_url = (expected or {}).get("exact_url")
    if canonical_url:
        entry["primary_urls"] = [str(canonical_url)]
    if candidate is None and not download:
        if canonical_url:
            entry["reason"] = "no_local_copy_registered_primary_url"
        return entry, None

    candidate = candidate or {}

    entry["paths"] = list(candidate.get("paths", []))
    for url in candidate.get("primary_urls", []):
        if download and url != canonical_url:
            raise CorpusError("download URL is not a registered canonical primary route")
        if url not in entry["primary_urls"]:
            entry["primary_urls"].append(url)

    local_error: str | None = None
    for raw_path in entry["paths"]:
        path = Path(raw_path)
        if not path.is_absolute():
            path = repo / path
        if not path.is_file():
            entry["warnings"].append(f"local_path_not_found:{raw_path}")
            local_error = "local_path_not_found"
            continue
        _assert_within(path.resolve(), repo, what="candidate path")
        if path.stat().st_size > DEFAULT_MAX_BYTES:
            entry["warnings"].append("local_file_too_large")
            local_error = "local_file_too_large"
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            entry.update(status="error", reason="local_read_failed", error=str(exc))
            return entry, None
        status, document, detail = _ingest_bytes(
            data=data,
            source_id=source_id,
            expected=expected,
            objects_dir=objects_dir,
            generated_at=generated_at,
            origin={"kind": "local", "path": str(path)},
        )
        entry.update(detail)
        if status == "available":
            return entry, document
        if status in {"needs_ocr", "rejected"}:
            return entry, None
        local_error = detail.get("reason") or status

    if entry["primary_urls"] and download:
        for url in entry["primary_urls"]:
            fetch = _fetch(url, max_attempts=MAX_HTTP_ATTEMPTS)
            entry["http_status"] = fetch.get("status")
            if not fetch.get("ok"):
                entry.update(
                    status="unavailable",
                    reason=fetch.get("error") or "download_failed",
                    error=str(fetch.get("error") or "download_failed"),
                )
                continue
            status, document, detail = _ingest_bytes(
                data=fetch["body"],
                source_id=source_id,
                expected=expected,
                objects_dir=objects_dir,
                generated_at=generated_at,
                origin={
                    "kind": "primary_url",
                    "primary_url": url,
                    "final_url": fetch.get("final_url"),
                },
                content_type=fetch.get("content_type"),
                http_status=fetch.get("status"),
            )
            entry.update(detail)
            if status == "available":
                return entry, document
            return entry, None
        return entry, None

    if entry["primary_urls"]:
        entry.update(status="unavailable", reason="download_disabled")
        return entry, None
    if local_error:
        entry.update(status="missing", reason=local_error)
    return entry, None


def _ingest_bytes(
    *,
    data: bytes,
    source_id: str,
    expected: Mapping[str, Any] | None,
    objects_dir: Path,
    generated_at: str,
    origin: Mapping[str, Any],
    content_type: str | None = None,
    http_status: int | None = None,
) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    sha256 = _sha256_bytes(data)
    version = sha256[:16]
    detail: dict[str, Any] = {
        "sha256": sha256,
        "version": version,
        "bytes": len(data),
        "retrieved_at": generated_at,
        "content_type": content_type,
        "http_status": http_status,
        "error": None,
    }
    origin_path = origin.get("path")
    suffix = Path(str(origin_path)).suffix.lower() if origin_path else None
    parsed = parse_document(
        data,
        url=origin.get("final_url") or origin.get("primary_url"),
        suffix=suffix,
        content_type=content_type,
        http_status=http_status,
    )
    detail["format"] = parsed["format"]
    page_starts = parsed.get("page_starts") or []
    detail["page_count"] = len(page_starts) or None

    if parsed.get("needs_ocr"):
        detail.update(status="needs_ocr", reason=parsed.get("reason") or "no_extractable_text")
        return "needs_ocr", None, detail

    if parsed.get("error_page"):
        detail.update(
            status="rejected",
            reason=parsed.get("error_page") or "error_page_detected",
        )
        return "rejected", None, detail

    text = str(parsed.get("text", ""))
    if any(0xD800 <= ord(character) <= 0xDFFF for character in text):
        detail.update(status="needs_ocr", reason="invalid_pdf_text_encoding")
        return "needs_ocr", None, detail
    # A DOI in the bibliography does not identify the containing article.
    identifiers = extract_identifiers(text[:6000])
    verified, evidence = validate_identity(identifiers, expected, title=parsed.get("title"))
    detail["identity_verified"] = verified
    detail["identity_evidence"] = evidence
    expected_title = _normalize_title((expected or {}).get("title"))
    front_matter = _normalize_title(text[:6000]) or ""
    if (
        verified
        and not evidence.get("matched") == ["title"]
        and expected_title
        and expected_title not in front_matter
    ):
        verified = False
        detail["identity_verified"] = False
        evidence["reason"] = "identifier_match_requires_front_matter_title"
    if not verified:
        detail.update(status="rejected", reason=evidence.get("reason") or "identity_unverified")
        return "rejected", None, detail

    sections = _build_sections(text, parsed.get("headings") or [], page_starts or None)
    detail["sections"] = sections
    _atomic_write_bytes(objects_dir / sha256, data)

    document = {
        "parser_version": "normalizer-v1",
        "source_id": source_id,
        "origin": dict(origin),
        "sha256": sha256,
        "version": version,
        "bytes": len(data),
        "format": parsed["format"],
        "content_type": content_type,
        "http_status": http_status,
        "retrieved_at": generated_at,
        "page_count": len(page_starts) or None,
        "page_starts": list(page_starts) or None,
        "sections": sections,
        "title": parsed.get("title"),
        "identity_evidence": evidence,
        "text": text,
        "text_sha256": _sha256_text(text),
        "completeness": "full_text"
        if len(text) > 10000
        and any(
            label[1] in {"methods", "results", "discussion"} for label in parsed.get("headings", [])
        )
        else "partial_text",
    }
    detail["status"] = "available"
    detail["reason"] = "parsed_and_identity_verified"
    return "available", document, detail


def _rejected_discovery_entry(candidate: Mapping[str, Any], generated_at: str) -> dict[str, Any]:
    source_class = candidate.get("source_class", "candidate")
    entry = _new_entry(str(candidate.get("provisional_id", "local:unknown")), generated_at)
    entry["paths"] = list(candidate.get("paths", []))
    entry.update(
        status="rejected",
        reason="identity_unverified_discovery"
        if source_class == "candidate"
        else f"{source_class}_not_indexed",
        error=None,
    )
    return entry


def _empty_discovery_report(generated_at: str, repo: Path, private: Path) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "repository": str(repo),
        "state_dir": str(private),
        "counts": {"scratch_candidates": 0, "repository_artifacts": 0, "candidates": 0},
        "scratch_candidates": [],
        "repository_artifacts_sample": [],
        "unresolved": [],
        "note": "explicit candidates supplied; no local discovery was performed",
    }


def _build_discovery_report(
    scanned: Sequence[Mapping[str, Any]],
    truncated: bool,
    generated_at: str,
    repo: Path,
    private: Path,
) -> dict[str, Any]:
    scratch = [item for item in scanned if item["source_class"] == "scratch"]
    artifacts = [item for item in scanned if item["source_class"] == "repository_artifact"]
    candidates = [item for item in scanned if item["source_class"] == "candidate"]
    unresolved = [
        {
            "relative_path": item["relative_path"],
            "reason": "scratch_file_requires_explicit_mapping",
            "bytes": item["bytes"],
        }
        for item in scratch
    ]
    for item in candidates:
        unresolved.append(
            {
                "relative_path": item["relative_path"],
                "reason": "no_canonical_identity_for_discovered_file",
                "bytes": item["bytes"],
            }
        )
    return {
        "generated_at": generated_at,
        "repository": str(repo),
        "state_dir": str(private),
        "truncated": truncated,
        "counts": {
            "scratch_candidates": len(scratch),
            "repository_artifacts": len(artifacts),
            "candidates": len(candidates),
        },
        "scratch_candidates": [
            {
                "relative_path": item["relative_path"],
                "bytes": item["bytes"],
                "extension": item["extension"],
                "modified_at": item["modified_at"],
                "status": "rejected",
                "reason": "scratch_file_requires_explicit_mapping",
            }
            for item in scratch
        ],
        "repository_artifacts_sample": [
            {
                "relative_path": item["relative_path"],
                "bytes": item["bytes"],
                "status": "rejected",
                "reason": "repository_artifact_not_indexed",
            }
            for item in artifacts[:50]
        ],
        "unresolved": unresolved,
        "note": (
            "Conservative discovery only. No scratch or artifact file is parsed or indexed; "
            "each needs an explicit canonical mapping and identity verification."
        ),
    }


# ---------------------------------------------------------------------------
# reading back
# ---------------------------------------------------------------------------


def load_documents(path: Path | str) -> list[dict[str, Any]]:
    """Read a normalized JSONL document store; blank lines are ignored."""
    documents: list[dict[str, Any]] = []
    source = Path(path)
    if not source.is_file():
        return documents
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        documents.append(json.loads(stripped))
    return documents


def load_manifest(state_dir: Path | str) -> dict[str, Any]:
    """Read the working manifest for a private state directory."""
    path = Path(state_dir) / "corpus" / "manifest.json"
    if not path.is_file():
        raise CorpusError(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def iter_objects(objects_dir: Path | str) -> Iterator[Path]:
    directory = Path(objects_dir)
    if not directory.is_dir():
        return
    for path in sorted(directory.iterdir()):
        if path.is_file() and not path.name.endswith(".tmp"):
            yield path
