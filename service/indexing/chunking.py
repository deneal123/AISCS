"""Paragraph-aware chunking primitives with exact character offsets."""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Sequence

CHUNK_TARGET_TOKENS = 1000
CHUNK_OVERLAP_TOKENS = 100
TOKEN_CHARS = 4  # deterministic token proxy: ~4 characters per token

PARAGRAPH_RE = re.compile(r"[^\n]+(?:\n(?![ \t]*\n)[^\n]*)*")
SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]*(?:\s+|$)")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + TOKEN_CHARS - 1) // TOKEN_CHARS)


def page_at(page_starts: Sequence[int], offset: int) -> int | None:
    if not page_starts:
        return None
    return bisect_right(page_starts, offset)


# ---------------------------------------------------------------------------
# chunking
# ---------------------------------------------------------------------------


def paragraph_units(text: str) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    for match in PARAGRAPH_RE.finditer(text):
        start, end = trim_span(text, match.start(), match.end())
        if start < end:
            units.append((start, end))
    return units


def trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def split_oversized(text: str, start: int, end: int, target_tokens: int) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    for match in SENTENCE_RE.finditer(text, start, end):
        s, e = trim_span(text, match.start(), match.end())
        if s < e:
            units.append((s, e))
    if units and estimate_tokens(text[start:end]) > target_tokens:
        return units
    return [(start, end)]


def pack_units(
    text: str, units: Sequence[tuple[int, int]], target_tokens: int, overlap_tokens: int
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    count = len(units)
    index = 0
    while index < count:
        cursor = index
        tokens = 0
        while cursor < count:
            unit_tokens = estimate_tokens(text[units[cursor][0] : units[cursor][1]])
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
            unit_tokens = estimate_tokens(text[units[back - 1][0] : units[back - 1][1]])
            if overlap + unit_tokens > overlap_tokens:
                break
            overlap += unit_tokens
            back -= 1
        index = cursor if back <= index else back
    return spans
