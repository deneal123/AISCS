"""Markdown books whose chapters come from a bold-line table of contents."""

from __future__ import annotations

import re
from typing import Any

from ...common.text import decode_bytes
from .blocks import TOC_TITLES, clean, title_key

_MD_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~:])")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)\s]+\)")
_MD_TABLE_RULE_RE = re.compile(r"^\|?[\s:|-]+\|?$")


def _md_inline(text: str) -> str:
    text = _MD_LINK_RE.sub(r"\1", re.sub(r"\*{2,3}|_{2,3}", "", text))
    return clean(_MD_ESCAPE_RE.sub(r"\1", text))


def _md_toc(lines: list[str]) -> tuple[list[tuple[int, str, str | None]], int, int]:
    """Return ``(level, title, chapter)`` items and the line range of the printed ToC."""
    start = next(
        (i for i, line in enumerate(lines) if title_key(_md_inline(line)) in TOC_TITLES), None
    )
    if start is None:
        return [], 0, 0
    items: list[tuple[int, str, str | None]] = []
    chapter: str | None = None
    end = start + 1
    for index in range(start + 1, len(lines)):
        raw = lines[index]
        if not raw.strip():
            continue
        bold = raw.strip().startswith("**")
        if not bold and not raw.startswith((" ", "\t")):
            break
        title = _md_inline(raw)
        if bold:
            chapter = title
            items.append((1, title, None))
        else:
            items.append((2, title, chapter))
        end = index + 1
    return items, start, end


def _md_blocks(text: str) -> list[tuple]:
    lines = text.replace("\r\n", "\n").split("\n")
    toc, toc_start, toc_end = _md_toc(lines)
    keys = [title_key(title) for _, title, _ in toc]
    last = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
    position = 0
    chapters: set[str] = set()
    blocks: list[tuple] = []
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or (toc and toc_start <= index < toc_end):
            continue
        if stripped.startswith("|"):
            if not _MD_TABLE_RULE_RE.match(stripped):
                cells = [_md_inline(c) for c in stripped.strip("|").split("|")]
                if row := " | ".join(c for c in cells if c):
                    blocks.append(("para", row))
            continue
        line = _md_inline(stripped)
        key = title_key(line)
        if not line or (index == last and key == "конец"):
            continue
        match = next((i for i in range(position, len(keys)) if keys[i] == key), None)
        if match is not None and len(line) <= 160:
            level, title, chapter = toc[match]
            if level == 2 and chapter and chapter not in chapters:
                blocks.append(("heading", 1, chapter, False))
                chapters.add(chapter)
            if level == 1:
                chapters.add(title)
            blocks.append(("heading", level, title if level == 1 else line, True))
            position = match + 1
            continue
        blocks.append(("para", line))
    return blocks


def extract_md(data: bytes) -> dict[str, Any]:
    text, _ = decode_bytes(data)
    return {"blocks": _md_blocks(text), "metadata": {}, "fragment": False}
