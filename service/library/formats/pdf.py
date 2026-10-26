"""PDF with a text layer: print sheets, spreads, running headers and watermarks."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ...common.errors import DataError
from .blocks import COMPOUND_RE, TEXT_BLOCKS, title_key
from .repair import hyphen_join

_PRINT_FOOTER_RE = re.compile(r"^\s*(?:\d+\s*/\s*\d+|Powered by TCPDF \(www\.tcpdf\.org\))\s*$")
_PAGE_HEADER_RE = re.compile(r"^\s*(\d{1,3})(?:\s+(\d{1,3}))?\s*$")
_RUNNING_NUMBER_RE = re.compile(r"^(\d{1,3})\s+\S|\S\s+(\d{1,3})$")
_PARAGRAPH_END = (".", "!", "?", ":", ";", "»", "…", '"')
_LIST_START_RE = re.compile(r"^(?:\d{1,2}[.)]|[a-zа-я][.)]|[–—•])\s")
_SPACED_HYPHEN_RE = re.compile(r"(?<=[^\W\d_]) -(?=[^\W\d_]|$)")


def pdf_page_texts(data: bytes) -> list[str]:
    import io
    import logging

    import pypdf

    logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding chatter only
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DataError("encrypted PDF books are not processed")
        return [page.extract_text() or "" for page in reader.pages]
    except pypdf.errors.PyPdfError as exc:
        raise DataError("malformed PDF book: " + type(exc).__name__) from exc


def _sheet_lines(texts: list[str]) -> list[list[str]]:
    """Normalized lines per sheet without print footers or per-page watermark lines."""
    pages = []
    for text in texts:
        lines = [" ".join(line.split()) for line in text.split("\n")]
        pages.append([line for line in lines if line and not _PRINT_FOOTER_RE.match(line)])
    counts = Counter(line for lines in pages for line in set(lines))
    # A short line printed on most sheets (a distributor watermark) is not book text.
    boilerplate = {
        line for line, n in counts.items() if n > 0.5 * len(pages) and len(line) < 80
    }
    suffixes = tuple(" " + line for line in boilerplate if len(line) >= 6)

    def strip(line: str) -> str:
        for suffix in suffixes:  # the watermark sometimes lands on the last text line
            if line.endswith(suffix):
                return line[: -len(suffix)]
        return line

    return [[strip(line) for line in lines if line not in boilerplate] for lines in pages]


def _running_number(line: str) -> int | None:
    pure = _PAGE_HEADER_RE.match(line)
    if pure:
        return int(pure.group(1))
    match = _RUNNING_NUMBER_RE.search(line)
    return int(match.group(1) or match.group(2)) if match else None


def _pdf_sheets(texts: list[str], layout: str) -> list[tuple[tuple[int, int], list[str]]]:
    """Drop footers, watermarks and repeated sheets; label sheets with printed pages.

    ``spreads``: two book pages per sheet with a bare ``"10 11"`` header; sheets are
    reordered by those numbers. ``pages``: one page per sheet with a running header
    (``"16 Title"`` or ``"Title 17"``); a first line counts as a header only when its
    number fits the sequence, so ``"Глава 1"`` on a chapter opening stays text."""
    unique: list[tuple[int, list[str]]] = []  # original sheet index keeps page arithmetic
    seen: set[str] = set()
    for index, lines in enumerate(_sheet_lines(texts)):
        key = "\n".join(lines)
        if lines and key not in seen:
            seen.add(key)
            unique.append((index, lines))
    if layout == "spreads":
        spans: list[tuple[tuple[int, int], list[str]]] = []
        previous: tuple[int, int] | None = None
        for _, lines in unique:
            header = _PAGE_HEADER_RE.match(lines[0])
            numbers = [int(g) for g in header.groups() if g] if header else []
            if header:
                lines = lines[1:]
            if len(numbers) == 2:
                span = (numbers[0], numbers[1])
            elif numbers:
                n = numbers[0]
                span = (n, n + 1) if n % 2 == 0 else (n - 1, n)
            else:  # unnumbered sheet keeps its place after the previous one
                span = (previous[1] + 1, previous[1] + 2) if previous else (1, 1)
            previous = span
            spans.append((span, lines))
        return sorted(spans, key=lambda item: item[0])
    candidates = [(index, _running_number(lines[0])) for index, lines in unique]
    offsets = Counter(n - i for i, n in candidates if n is not None)
    offset = offsets.most_common(1)[0][0] if offsets else 1
    sheets = []
    for (index, lines), (_, number) in zip(unique, candidates, strict=True):
        expected = index + offset
        if number is not None and abs(number - expected) <= 1:
            lines = lines[1:]
            expected = number
        sheets.append(((expected, expected), lines))
    return sheets


def _toc_lines(lines: list[str], items: list[dict[str, Any]]) -> dict[int, tuple[dict, int]]:
    """Locate printed ToC titles that span one to three consecutive lines."""
    found: dict[int, tuple[dict, int]] = {}
    cursor = 0
    for item in items:
        key = title_key(item.get("match") or item["title"])
        for start in range(cursor, len(lines)):
            joined = [title_key(" ".join(lines[start : start + n])) for n in (1, 2, 3)]
            size = next(
                (n for n, candidate in zip((1, 2, 3), joined, strict=True) if candidate == key),
                None,
            )
            if size and start + size <= len(lines):
                found[start] = (item, size)
                cursor = start + size
                break
    return found


def _pdf_blocks(sheets: list[tuple[tuple[int, int], list[str]]], toc: list[dict]) -> list[tuple]:
    compounds = {
        m.group(0).casefold()
        for _, lines in sheets
        for line in lines
        for m in COMPOUND_RE.finditer(line.removesuffix("-"))
    }
    blocks: list[tuple] = []
    open_paragraph = False
    for (first, last), lines in sheets:
        blocks.append(("page", str(first) if first == last else f"{first}–{last}"))
        items = [item for item in toc if first <= int(item["page"]) <= last]
        headings = _toc_lines(lines, items)
        placed = {id(item) for item, _ in headings.values()}
        for item in items:
            if id(item) not in placed:  # title not found verbatim: place at the sheet start
                blocks.append(("heading", int(item["level"]), item["title"], False))
        lines = [_SPACED_HYPHEN_RE.sub("-", line) for line in lines]
        lengths = sorted(len(line) for line in lines if len(line) > 20)
        typical = lengths[int(len(lengths) * 0.75)] if lengths else 60
        paragraph, kind = "", "para"

        def flush() -> None:
            nonlocal paragraph, kind
            if paragraph:
                blocks.append((kind, paragraph))
            paragraph, kind = "", "para"

        index = 0
        while index < len(lines):
            if index in headings:
                flush()
                item, size = headings[index]
                blocks.append(("heading", int(item["level"]), item["title"], True))
                index += size
                open_paragraph = False
                continue
            line = lines[index]
            if not paragraph and open_paragraph and line[:1].islower():
                previous = max(i for i, b in enumerate(blocks) if b[0] in TEXT_BLOCKS)
                text = blocks[previous][1]
                kind = "cont"
                if text.endswith("-") and text[-2:-1].isalpha():
                    blocks[previous] = (blocks[previous][0], hyphen_join(text, line, compounds))
                    kind = "join"
            elif paragraph and _LIST_START_RE.match(line):
                flush()
            if paragraph.endswith("-") and paragraph[-2:-1].isalpha() and line[:1].islower():
                paragraph = hyphen_join(paragraph, line, compounds) + line
            else:
                paragraph = f"{paragraph} {line}" if paragraph else line
            open_paragraph = True
            if line.endswith(_PARAGRAPH_END) and len(line) < 0.8 * typical:
                flush()
                open_paragraph = False
            index += 1
        flush()
    return blocks


def extract_pdf(data: bytes, *, options: dict[str, Any]) -> dict[str, Any]:
    texts = pdf_page_texts(data)
    if not any(t.strip() for t in texts):
        raise DataError("PDF has no text layer; OCR is required")
    sheets = _pdf_sheets(texts, options.get("pdf_layout", "pages"))
    return {
        "blocks": _pdf_blocks(sheets, options.get("toc") or []),
        "metadata": {"pdf_pages": len(texts), "unique_sheets": len(sheets)},
        "fragment": False,
    }
