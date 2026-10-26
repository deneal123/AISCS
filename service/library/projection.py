"""Library projection: section-bounded chunks and the Book → Section → Chunk graph."""

from __future__ import annotations

from bisect import bisect_right
from typing import Any

from ..common.errors import DataError
from ..common.hashing import sha256_text
from ..indexing.chunking import (
    PARAGRAPH_RE,
    estimate_tokens,
    pack_units,
    split_oversized,
    trim_span,
)
from ..indexing.generations import digest
from .catalog import citation

CHUNKER_VERSION = "library-chunker-v1"
CHUNK_TARGET_TOKENS = 700
CHUNK_OVERLAP_TOKENS = 80
MIN_SEGMENT_CHARS = 1200




def _units(text: str, start: int, end: int) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    hard_limit = CHUNK_TARGET_TOKENS * 4 * 2
    for match in PARAGRAPH_RE.finditer(text, start, end):
        s, e = trim_span(text, match.start(), match.end())
        if s >= e:
            continue
        pieces = (
            split_oversized(text, s, e, CHUNK_TARGET_TOKENS)
            if estimate_tokens(text[s:e]) > CHUNK_TARGET_TOKENS
            else [(s, e)]
        )
        for ps, pe in pieces:
            # A run-on "sentence" from a broken conversion is cut at whitespace.
            while pe - ps > hard_limit:
                cut = text.rfind(" ", ps + hard_limit // 4, ps + hard_limit // 2)
                if cut <= ps:
                    cut = ps + hard_limit // 2
                units.append(trim_span(text, ps, cut))
                ps = cut
            units.append(trim_span(text, ps, pe))
    return [(s, e) for s, e in units if s < e]


def _page_label(pages: list[dict[str, Any]], offset: int) -> str | None:
    if not pages:
        return None
    position = bisect_right([p["char"] for p in pages], offset) - 1
    return pages[position]["page"] if position >= 0 else pages[0]["page"]


def chunk_book(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Section-bounded paragraph packing with exact offsets into the normalized book."""
    text, sections, pages = document["text"], document["sections"], document["page_starts"]
    starts = sorted({0, *(s["char_start"] for s in sections)})
    spans = [(a, b) for a, b in zip(starts, [*starts[1:], len(text)], strict=True) if b > a]
    segments: list[tuple[int, int]] = []
    for a, b in spans:
        if segments and segments[-1][1] - segments[-1][0] < MIN_SEGMENT_CHARS:
            segments[-1] = (segments[-1][0], b)
        else:
            segments.append((a, b))
    section_starts = [s["char_start"] for s in sections]
    chunks: list[dict[str, Any]] = []
    for a, b in segments:
        units = _units(text, a, b)
        if not units:
            continue
        for start, end in pack_units(text, units, CHUNK_TARGET_TOKENS, CHUNK_OVERLAP_TOKENS):
            position = bisect_right(section_starts, start) - 1
            section = sections[position] if position >= 0 else None
            chunks.append(
                {
                    "char_start": start,
                    "char_end": end,
                    "section_index": position if position >= 0 else None,
                    "section_path": section["path"] if section else [],
                    "page_start": _page_label(pages, start),
                    "page_end": _page_label(pages, max(start, end - 1)),
                    "text": text[start:end],
                }
            )
    for index, chunk in enumerate(chunks):
        text_hash = sha256_text(chunk["text"])
        chunk.update(
            chunk_id=f"{document['book_id']}::{document['sha256'][:12]}::{index:05d}"
            f"::{text_hash[:12]}",
            chunk_index=index,
            chunk_count=len(chunks),
            text_sha256=text_hash,
        )
    return chunks


def _edge(kind: str, source: str, target: str, book_id: str) -> dict[str, Any]:
    return {
        "id": "edge:" + digest([kind, source, target])[:24],
        "source": source,
        "target": target,
        "type": kind,
        "status": "verified",
        "provenance": {"book_id": book_id, "chunker": CHUNKER_VERSION},
    }


def project_library(catalog: dict[str, Any], documents: list[dict[str, Any]]) -> dict[str, Any]:
    books = {b["book_id"]: b for b in catalog["books"]}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for document in sorted(documents, key=lambda d: d["book_id"]):
        book_id = document["book_id"]
        book = books.get(book_id)
        if book is None or book["sha256"] != document["sha256"]:
            raise DataError("prepared book is not in the catalog: " + book_id)
        book_node = "book:" + book_id
        contents = [s["title"] for s in document["sections"] if s["level"] <= 2]
        nodes.append(
            {
                "id": book_node,
                "type": "Book",
                "text": citation(book) + "\n" + "; ".join(contents),
                "metadata": {
                    "book_id": book_id,
                    "citation": citation(book),
                    "title": book["title"],
                    "authors": book["authors"],
                    "year": book.get("year"),
                    "completeness": book["completeness"],
                    "format": book["format"],
                    "sha256": document["sha256"],
                    "text_sha256": document["text_sha256"],
                },
            }
        )
        section_ids: list[str] = []
        parents: list[tuple[int, str]] = []
        for index, section in enumerate(document["sections"]):
            node_id = f"section:{book_id}:{index:04d}"
            section_ids.append(node_id)
            while parents and parents[-1][0] >= section["level"]:
                parents.pop()
            nodes.append(
                {
                    "id": node_id,
                    "type": "Section",
                    "text": " › ".join(section["path"]),
                    "metadata": {
                        "book_id": book_id,
                        "level": section["level"],
                        "title": section["title"],
                        "path": section["path"],
                        "char_start": section["char_start"],
                        "char_end": section["char_end"],
                        "page": _page_label(document["page_starts"], section["char_start"]),
                    },
                }
            )
            edges.append(
                _edge("section_of", node_id, parents[-1][1] if parents else book_node, book_id)
            )
            parents.append((section["level"], node_id))
        header = citation(book) + (
            " (ознакомительный фрагмент)" if book["completeness"] == "fragment" else ""
        )
        previous: str | None = None
        for chunk in chunk_book(document):
            parent = (
                section_ids[chunk["section_index"]]
                if chunk["section_index"] is not None
                else book_node
            )
            nodes.append(
                {
                    "id": chunk["chunk_id"],
                    "type": "Chunk",
                    "text": chunk["text"],
                    "metadata": {
                        "book_id": book_id,
                        "doc_sha256": document["sha256"],
                        "text_sha256": chunk["text_sha256"],
                        "chunk_index": chunk["chunk_index"],
                        "chunk_count": chunk["chunk_count"],
                        "char_start": chunk["char_start"],
                        "char_end": chunk["char_end"],
                        "page_start": chunk["page_start"],
                        "page_end": chunk["page_end"],
                        "section_id": parent,
                        "section_path": chunk["section_path"],
                        "completeness": book["completeness"],
                        "embedding_header": header + "\n" + " › ".join(chunk["section_path"]),
                    },
                }
            )
            edges.append(_edge("fragment_of", chunk["chunk_id"], parent, book_id))
            if previous:
                edges.append(_edge("next", previous, chunk["chunk_id"], book_id))
            previous = chunk["chunk_id"]
    return {"nodes": nodes, "edges": edges}
