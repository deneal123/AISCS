"""Text and structure repair: hyphenation, OCR word splits, inline headings, heading limits."""

from __future__ import annotations

import re
from collections import Counter

from .blocks import TEXT_BLOCKS, WORD_RE, clean

_INNER_HYPHEN_RE = re.compile(r"\b([^\W\d_]+)-([^\W\d_]+)\b")


def _vocabulary(blocks: list[tuple]) -> set[str]:
    words: set[str] = set()
    for block in blocks:
        if block[0] in TEXT_BLOCKS:
            words.update(w.casefold() for w in WORD_RE.findall(block[1]))
    return words


def join_inner_hyphens(blocks: list[tuple]) -> list[tuple]:
    """Join typesetting hyphens such as ``ка-федрой`` only when the joined word occurs
    elsewhere in the same book; genuine compounds (``из-за``, ``научно-популярный``) stay."""
    words = _vocabulary(blocks)

    def repl(match: re.Match) -> str:
        left, right = match.group(1), match.group(2)
        if right[:1].islower() and (left + right).casefold() in words:
            return left + right
        return match.group(0)

    joined = []
    for block in blocks:
        if block[0] in TEXT_BLOCKS:
            block = (block[0], _INNER_HYPHEN_RE.sub(repl, block[1]))
        joined.append(block)
    return joined


# The right fragment is a lookahead so overlapping pairs ("и ауди тории") are all seen.
_SPLIT_WORD_RE = re.compile(r"\b([^\W\d_]+) (?=([^\W\d_]+)\b)")


def join_split_words(blocks: list[tuple]) -> list[tuple]:
    """Repair OCR spaces inside words (``дей ствительно``, ``чт о``).

    Two fragments are joined only when the joined word occurs whole in the same book
    and one fragment never occurs on its own outside such pairs; ordinary phrases
    (``во время``, ``так и``) consist of free-standing words and stay apart."""
    texts = [block[1] for block in blocks if block[0] in TEXT_BLOCKS]
    counts = Counter(w.casefold() for text in texts for w in WORD_RE.findall(text))
    inside: Counter = Counter()
    for text in texts:
        for match in _SPLIT_WORD_RE.finditer(text):
            left, right = match.group(1).casefold(), match.group(2).casefold()
            if match.group(2)[:1].islower() and counts.get(left + right, 0) > 0:
                inside[left] += 1
                inside[right] += 1

    def repl(match: re.Match) -> str:
        left, right = match.group(1), match.group(2)
        a, b = left.casefold(), right.casefold()
        bound = counts[a] <= inside[a] or counts[b] <= inside[b]
        if right[:1].islower() and counts.get(a + b, 0) > 0 and bound:
            return left  # drop the space; the right fragment follows untouched
        return match.group(0)

    repaired = []
    for block in blocks:
        if block[0] in TEXT_BLOCKS:
            block = (block[0], _SPLIT_WORD_RE.sub(repl, block[1]))
        repaired.append(block)
    return repaired


def hyphen_join(left: str, right: str, compounds: set[str]) -> str:
    """Join a line-end hyphenation; keep the hyphen only for compounds seen in the book."""
    left_words, right_word = WORD_RE.findall(left[:-1]), WORD_RE.match(right)
    candidate = (left_words[-1] + "-" + right_word.group(0)).casefold() if (
        left_words and right_word
    ) else ""
    return left if candidate in compounds else left[:-1]


# ---------------------------------------------------------------------------
# Catalog-driven structure repair
# ---------------------------------------------------------------------------

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9}
_INLINE_NUMBER_RE = re.compile(
    r"(?<![\w.])(I{1,3}|IV|V|VI{1,3}|IX)\.((?:\s?\d{1,2}\.)+)(?=\s|[^\W\d_])"
)
_CHAPTER_NUMBER_RE = re.compile(r"^(I{1,3}|IV|V|VI{1,3}|IX)\.\s")


def _successors(previous: tuple[int, ...]) -> set[tuple[int, ...]]:
    """Numbers that may follow ``previous``: its first child or the next sibling of any
    ancestor. Cross-references (``см. II. 6. 1``) break this order and stay text."""
    following = {previous + (1,)}
    following.update(previous[:k] + (previous[k] + 1,) for k in range(len(previous)))
    return following


def split_inline_headings(blocks: list[tuple]) -> list[tuple]:
    """Recover ``III. 1. 2.`` headings that a converter flattened into running text."""
    repaired: list[tuple] = []
    previous: tuple[int, ...] | None = None
    for block in blocks:
        if block[0] == "heading":
            match = _CHAPTER_NUMBER_RE.match(clean(block[2]))
            previous = (_ROMAN[match.group(1)],) if match else previous
            repaired.append(block)
            continue
        if block[0] not in TEXT_BLOCKS or previous is None:
            repaired.append(block)
            continue
        text, cursor, kind = block[1], 0, block[0]
        matches = list(_INLINE_NUMBER_RE.finditer(text))
        for position, match in enumerate(matches):
            number = (_ROMAN[match.group(1)], *map(int, re.findall(r"\d+", match.group(2))))
            if number not in _successors(previous):
                continue
            if text[cursor : match.start()].strip():
                repaired.append((kind, text[cursor : match.start()]))
                kind = "para"
            stop = matches[position + 1].start() if position + 1 < len(matches) else len(text)
            words = text[match.end() : stop].split()
            label = f"{match.group(1)}." + "".join(f"{n}." for n in number[1:])
            preview = " ".join(words[:8]) + ("…" if len(words) > 8 else "")
            repaired.append(("heading", len(number), f"{label} {preview}".strip(), False))
            previous, cursor = number, match.start()
        if text[cursor:].strip():
            repaired.append((kind, text[cursor:]))
    return repaired


def limit_heading_levels(blocks: list[tuple], max_level: int) -> list[tuple]:
    """Treat deeper headings (figure labels exported as ``h5``) as ordinary paragraphs."""
    limited: list[tuple] = []
    for block in blocks:
        if block[0] == "heading" and block[1] > max_level:
            if block[3]:
                limited.append(("para", block[2]))
            continue
        limited.append(block)
    return limited
