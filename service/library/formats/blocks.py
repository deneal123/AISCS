"""Block model shared by all book formats and its assembly into text with exact offsets.

Blocks are ``("heading", level, title, in_text)``, ``("para", text)``, ``("cont", text)``
(the same paragraph continued after a page break), ``("join", text)`` (a word split by
a page break) and ``("page", label)`` (the following text starts that printed page).
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any

from ...common.errors import DataError

TOC_TITLES = frozenset({"содержание", "оглавление"})
NOTES_TITLE = "Примечания"
TEXT_BLOCKS = frozenset({"para", "cont", "join"})

_SPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"[^\W\d_]+")
COMPOUND_RE = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)+")


def clean(text: str) -> str:
    """Single-line NFC text without soft hyphens or repeated whitespace."""
    text = unicodedata.normalize("NFC", text).replace("\u00ad", "").replace("\ufeff", "")
    return _SPACE_RE.sub(" ", text).strip()


def title_key(text: str) -> str:
    """Letters and digits only, case-folded; tolerant to spacing, quotes and ё."""
    return "".join(ch for ch in text.casefold().replace("ё", "е") if ch.isalnum())


def exclude_sections(blocks: list[tuple], prefixes: list[str]) -> tuple[list[tuple], list[str]]:
    """Drop a printed table of contents and catalog-listed sections with their children."""
    keys = [title_key(p) for p in prefixes]
    kept: list[tuple] = []
    removed: list[str] = []
    skip_level: int | None = None
    for block in blocks:
        if block[0] == "heading":
            level, title = block[1], block[2]
            if skip_level is not None and level <= skip_level:
                skip_level = None
            key = title_key(title)
            if skip_level is None and (
                (level == 1 and key in TOC_TITLES) or any(key.startswith(k) for k in keys if k)
            ):
                skip_level = level
                removed.append(clean(title))
                continue
        if skip_level is None or block[0] == "page":
            kept.append(block)
    return kept, removed


def assemble(blocks: list[tuple]) -> dict[str, Any]:
    """Concatenate blocks with blank-line paragraph breaks and exact offsets."""
    parts: list[str] = []
    length = 0
    sections: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    pending_pages: list[str] = []
    pending_sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []

    def emit(separator: str, text: str) -> None:
        nonlocal length
        if parts:
            parts.append(separator)
            length += len(separator)
        for label in pending_pages:
            if pages and pages[-1]["char"] == length:
                pages[-1] = {"page": label, "char": length}
            elif not pages or pages[-1]["page"] != label:
                pages.append({"page": label, "char": length})
        pending_pages.clear()
        for section in pending_sections:
            section["char_start"] = length
            sections.append(section)
        pending_sections.clear()
        parts.append(text)
        length += len(text)

    for block in blocks:
        kind = block[0]
        if kind == "page":
            pending_pages.append(str(block[1]))
            continue
        if kind == "heading":
            _, level, title, in_text = block
            title = clean(title)
            if not title:
                continue
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            pending_sections.append(
                {
                    "level": level,
                    "title": title,
                    "path": [t for _, t in stack],
                    "in_text": bool(in_text),
                }
            )
            if in_text:
                emit("\n\n", title)
            continue
        text = clean(block[1])
        if text:
            emit({"cont": " ", "join": ""}.get(kind, "\n\n"), text)
    text = "".join(parts)
    for position, section in enumerate(sections):
        section["char_end"] = (
            sections[position + 1]["char_start"] if position + 1 < len(sections) else len(text)
        )
    return {"text": text, "sections": sections, "page_starts": pages}


def safe_xml(data: bytes) -> ET.Element:
    """Parse local XML books, refusing entity declarations (no expansion attacks)."""
    if b"<!ENTITY" in data or re.search(rb"<!DOCTYPE[^>]*\[", data[:65536]):
        raise DataError("XML entity declarations are refused")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise DataError("malformed XML book: " + str(exc)) from exc
