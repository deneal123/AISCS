"""Chunking of normalized corpus documents with fixed coordinates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...common.errors import CorpusError
from ...common.hashing import sha256_text
from ...indexing.chunking import (
    CHUNK_OVERLAP_TOKENS,
    CHUNK_TARGET_TOKENS,
    estimate_tokens,
    pack_units,
    page_at,
    paragraph_units,
    split_oversized,
)


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
    chunks: list[dict[str, Any]] = []
    for document in documents:
        text = str(document.get("text", ""))
        source_id = str(document.get("source_id", "unknown"))
        doc_sha = str(document.get("sha256", ""))
        page_starts = document.get("page_starts") or []
        sections = list(document.get("sections") or [])
        units: list[tuple[int, int]] = []
        for start, end in paragraph_units(text):
            if estimate_tokens(text[start:end]) > target_tokens:
                units.extend(split_oversized(text, start, end, target_tokens))
            else:
                units.append((start, end))
        if not units and text:
            units = split_oversized(text, 0, len(text), target_tokens)
        spans = pack_units(text, units, target_tokens, overlap_tokens)
        for index, (start, end) in enumerate(spans):
            body = text[start:end]
            text_hash = sha256_text(body)
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
                    "page_start": page_at(page_starts, start),
                    "page_end": page_at(page_starts, max(start, end - 1)),
                    "section_labels": _overlap_labels(sections, start, end),
                    "token_estimate": estimate_tokens(body),
                    "text": body,
                    "text_sha256": text_hash,
                    "chunk_sha256": sha256_text(f"{chunk_id}\0{body}"),
                }
            )
    return chunks
