"""Parsing of HTML, XML, PDF and text into normalized text, headings and sections."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from html.parser import HTMLParser
from typing import Any

from ...common.text import decode_bytes
from ...indexing.chunking import page_at
from .identity import DOI_RE, TITLE_STOPWORDS
from .text import WHITESPACE_RE, detect_format, looks_like_markup, normalize_fragment

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
        return normalize_fragment(re.sub(r"(?s)<[^>]+>", " ", stripped)), []
    text = normalize_fragment(extractor.text())
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
        pages.append(normalize_fragment(raw))
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
    if fmt in {"html", "xml"} or looks_like_markup(decoded):
        if fmt == "txt" and looks_like_markup(decoded):
            fmt = "html"
            result["format"] = "html"
        text, headings = _markup_text(decoded)
    else:
        text = normalize_fragment(decoded)
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
        if candidate.casefold().strip(" .:-\u2014") in TITLE_STOPWORDS:
            continue
        if DOI_RE.search(candidate) and len(candidate) < 40:
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
            words = WHITESPACE_RE.split(text.strip())
            if len(words) <= 400:
                return reason
    if url and not text.strip():
        return "error_page_detected"
    return None


# ---------------------------------------------------------------------------
# section construction
# ---------------------------------------------------------------------------


def build_sections(
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
                "page": page_at(page_starts, offset) if page_starts else None,
                "char_start": offset,
                "char_end": char_end,
            }
        )
    return sections
