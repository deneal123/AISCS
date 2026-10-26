"""FictionBook 2 extraction: sections, notes and retailer-preview detection."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from ...common.errors import DataError
from .blocks import NOTES_TITLE, clean, safe_xml

FRAGMENT_MARK = "конец ознакомительного фрагмента"
FB2 = "{http://www.gribuser.ru/xml/fictionbook/2.0}"


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _text(element: ET.Element | None) -> str:
    return clean("".join(element.itertext())) if element is not None else ""


def _title(element: ET.Element | None) -> str:
    if element is None:
        return ""
    lines = [_text(child) for child in element if _local(child.tag) == "p"]
    return clean(" ".join(line for line in lines if line)) or _text(element)


def fb2_metadata(root: ET.Element) -> dict[str, Any]:
    description = root.find(FB2 + "description")
    info = description.find(FB2 + "title-info") if description is not None else None
    publish = description.find(FB2 + "publish-info") if description is not None else None
    if info is None:
        return {}

    def person(element: ET.Element) -> str:
        names = [
            clean(element.findtext(FB2 + k) or "")
            for k in ("last-name", "first-name", "middle-name")
        ]
        return " ".join(n for n in names if n) or clean(element.findtext(FB2 + "nickname") or "")

    def field(element: ET.Element | None, name: str) -> str:
        return clean(element.findtext(FB2 + name) or "") if element is not None else ""

    metadata = {
        "title": field(info, "book-title"),
        "authors": [p for a in info.findall(FB2 + "author") if (p := person(a))],
        "translators": [p for a in info.findall(FB2 + "translator") if (p := person(a))],
        "language": field(info, "lang"),
        "source_language": field(info, "src-lang"),
        "genres": [g for e in info.findall(FB2 + "genre") if (g := clean(e.text or ""))],
        "annotation": _text(info.find(FB2 + "annotation")),
        "publisher": field(publish, "publisher"),
        "city": field(publish, "city"),
        "year": field(publish, "year"),
        "isbn": field(publish, "isbn"),
    }
    return {k: v for k, v in metadata.items() if v}


class _FragmentEnd(Exception):
    """A retailer preview ends here; everything after it is advertising."""


def _fb2_blocks(root: ET.Element) -> tuple[list[tuple], bool]:
    blocks: list[tuple] = []

    def paragraph(element: ET.Element) -> None:
        text = _text(element)
        if FRAGMENT_MARK in text.casefold():
            raise _FragmentEnd
        if text:
            blocks.append(("para", text))

    def walk(element: ET.Element, depth: int) -> None:
        for child in element:
            tag = _local(child.tag)
            if tag == "section":
                title = _title(child.find(FB2 + "title"))
                if FRAGMENT_MARK in title.casefold():
                    raise _FragmentEnd
                if title:
                    blocks.append(("heading", depth + 1, title, True))
                    walk(child, depth + 1)
                else:
                    walk(child, depth)
            elif tag in {"title", "image", "empty-line", "binary"}:
                continue
            elif tag in {"p", "subtitle", "v", "text-author"}:
                paragraph(child)
            elif tag == "table":
                for row in child.iter(FB2 + "tr"):
                    cells = [_text(c) for c in row if _local(c.tag) in {"td", "th"}]
                    if any(cells):
                        blocks.append(("para", " | ".join(cells)))
            else:  # epigraph, cite, poem, stanza, annotation
                walk(child, depth)

    bodies = root.findall(FB2 + "body")
    note_names = {"notes", "comments", "footnotes"}
    fragment = False
    try:
        for body in bodies:
            if body.get("name") not in note_names:
                walk(body, 0)
    except _FragmentEnd:
        fragment = True
    notes: list[str] = []
    for body in bodies:
        if body.get("name") not in note_names:
            continue
        for section in body.iter(FB2 + "section"):
            lines = [
                _text(c)
                for c in section
                if _local(c.tag) in {"p", "v", "subtitle", "text-author", "cite", "poem"}
            ]
            text = clean(" ".join(line for line in lines if line))
            if not text:
                continue
            label = _title(section.find(FB2 + "title")).strip("[]() ")
            notes.append(f"[{label}] {text}" if label else text)
    if notes:
        blocks.append(("heading", 1, NOTES_TITLE, True))
        blocks.extend(("para", note) for note in notes)
    return blocks, fragment


def extract_fb2(data: bytes) -> dict[str, Any]:
    root = safe_xml(data)
    if _local(root.tag) != "FictionBook":
        raise DataError("not an FB2 FictionBook document")
    blocks, fragment = _fb2_blocks(root)
    return {"blocks": blocks, "metadata": fb2_metadata(root), "fragment": fragment}
