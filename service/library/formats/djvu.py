"""DjVu XML (Internet Archive OCR layer) with sections from a curated printed ToC."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from ...common.errors import DataError
from .blocks import COMPOUND_RE, clean, safe_xml, title_key
from .repair import hyphen_join


def _djvu_pages(root: ET.Element) -> list[list[list[str]]]:
    pages = []
    for obj in root.iter("OBJECT"):
        paragraphs = []
        for paragraph in obj.iter("PARAGRAPH"):
            lines = [
                clean("".join(word.text or "" for word in line.iter("WORD")))
                for line in paragraph.iter("LINE")
            ]
            if lines := [line for line in lines if line]:
                paragraphs.append(lines)
        pages.append(paragraphs)
    return pages


def _join_ocr_lines(lines: list[str], compounds: set[str]) -> str:
    out = ""
    for line in lines:
        if out.endswith("-") and out[-2:-1].isalpha() and line[:1].islower():
            out = hyphen_join(out, line, compounds) + line
        else:
            out = (out + " " + line) if out else line
    return out


def _djvu_blocks(root: ET.Element, toc: list[dict[str, Any]]) -> list[tuple]:
    pages = _djvu_pages(root)
    compounds = {
        m.group(0).casefold()
        for page in pages
        for paragraph in page
        for line in paragraph
        for m in COMPOUND_RE.finditer(line.removesuffix("-"))
    }
    by_page: dict[int, list[dict[str, Any]]] = {}
    for item in toc:
        by_page.setdefault(int(item["page"]), []).append(item)
    blocks: list[tuple] = []
    last_text: int | None = None
    for index, paragraphs in enumerate(pages):
        texts = [_join_ocr_lines(lines, compounds) for lines in paragraphs]
        # The printed running number is a lone number at the top or bottom of the page.
        while texts and re.fullmatch(r"\d{1,3}", texts[-1]):
            texts.pop()
        while texts and re.fullmatch(r"\d{1,3}", texts[0]):
            texts.pop(0)
        blocks.append(("page", index))
        placed: dict[int, list[dict[str, Any]]] = {}
        for item in by_page.get(index, []):
            key = title_key(item.get("match") or item["title"])[:14]
            found = next((i for i, t in enumerate(texts) if title_key(t).startswith(key)), 0)
            placed.setdefault(found, []).append(item)
        if not texts:
            for item in placed.get(0, []):
                blocks.append(("heading", int(item["level"]), item["title"], False))
            continue
        for position, text in enumerate(texts):
            for item in placed.get(position, []):
                blocks.append(("heading", int(item["level"]), item["title"], False))
            kind = "para"
            if position == 0 and not placed.get(0) and text[:1].islower() and last_text is not None:
                previous = blocks[last_text]
                kind = "cont"
                if previous[1].endswith("-") and previous[1][-2:-1].isalpha():
                    blocks[last_text] = (previous[0], hyphen_join(previous[1], text, compounds))
                    kind = "join"
            blocks.append((kind, text))
            last_text = len(blocks) - 1
    return blocks


def extract_djvu_xml(data: bytes, *, toc: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    root = safe_xml(data)
    if root.tag != "DjVuXML":
        raise DataError("not a DjVuXML document")
    return {"blocks": _djvu_blocks(root, toc or []), "metadata": {}, "fragment": False}
