"""Private, immutable transcript evidence and bounded structured notes.

Quote validation proves provenance, not semantic entailment or factual truth.
No source or model text belongs in diagnostics, events or object reprs.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from service.domain.video_summary.claim_alignment import (
    drops_relevant_condition,
    polarity_conflicts,
)
from service.domain.video_summary.source import MAX_CHUNKS, VideoSummaryFailure, VideoTranscript

# Source text is present both in the private prompt and the literal quote schema.
# Bound each authoring operation independently, rather than asking a small model
# to select evidence across several minutes in one function response.
CHUNK_CHAR_BUDGET = 4000

_NUMBER_RE = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)?(?:\s*%)?(?!\w)")


def _validate_claim_alignment(text: str, evidence: tuple[SupportingEvidence, ...]) -> None:
    """Reject obvious polarity, condition, and numeric drift against cited quotes.

    This is a conservative consistency check, not a semantic-entailment proof.
    """
    quote_contexts = tuple(item.context for item in evidence)
    quotes = " ".join(quote_contexts)
    if polarity_conflicts(text, quote_contexts):
        raise NotesProtocolFailure("claim_polarity")
    if drops_relevant_condition(text, quote_contexts):
        raise NotesProtocolFailure("claim_condition")
    if set(_NUMBER_RE.findall(text)) - set(_NUMBER_RE.findall(quotes)):
        raise NotesProtocolFailure("claim_quantity")


class NotesProtocolFailure(VideoSummaryFailure):
    """Private closed validator reason; never carries source or model text."""

    def __init__(self, reason: str):
        super().__init__("protocol")
        self.reason = reason


def normalized(text: str) -> str:
    return " ".join(text.split())


def digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class EvidenceCue:
    cue_id: str
    second: float
    text: str = field(repr=False)
    last_second: float | None = None
    source_ids: tuple[str, ...] = ()

    @property
    def end(self) -> float:
        return self.second if self.last_second is None else self.last_second


def _paragraph(parts: list[EvidenceCue]) -> EvidenceCue:
    return EvidenceCue(
        parts[0].cue_id,
        parts[0].second,
        " ".join(part.text for part in parts),
        parts[-1].end,
        tuple(cid for part in parts for cid in (part.source_ids or (part.cue_id,))),
    )


def _paragraphs(parts: list[EvidenceCue]) -> tuple[EvidenceCue, ...]:
    """Retain neighbouring caption context in deterministic bounded source blocks."""
    result = []
    buffer: list[EvidenceCue] = []
    size = 0
    for part in parts:
        if buffer and (
            size + len(part.text) + 1 > 600
            or part.second - buffer[0].second > 20
            or part.second <= buffer[-1].second
        ):
            result.append(_paragraph(buffer))
            buffer, size = [], 0
        buffer.append(part)
        size += len(part.text) + 1
    if buffer:
        result.append(_paragraph(buffer))
    return tuple(result)


@dataclass(frozen=True, slots=True, repr=False)
class EvidenceChunk:
    index: int
    source_digest: str
    cues: tuple[EvidenceCue, ...]

    @property
    def start(self) -> float:
        return self.cues[0].second

    @property
    def end(self) -> float:
        return self.cues[-1].end

    def prompt(self) -> str:
        return json.dumps(
            [{"cue_id": c.cue_id, "second": c.second, "text": c.text} for c in self.cues],
            ensure_ascii=False,
        )

    def coverage_groups(self) -> dict[str, tuple[EvidenceCue, ...]]:
        names = ("beginning", "middle", "end")
        return {
            name: tuple(
                cue for i, cue in enumerate(self.cues) if min(2, i * 3 // len(self.cues)) == group
            )
            for group, name in enumerate(names)
            if any(min(2, i * 3 // len(self.cues)) == group for i in range(len(self.cues)))
        }


@dataclass(frozen=True, slots=True, repr=False)
class VideoEvidenceIndex:
    source_digest: str
    chunks: tuple[EvidenceChunk, ...]

    @classmethod
    def create(
        cls, source: VideoTranscript, interval: tuple[int, int] | None = None
    ) -> VideoEvidenceIndex:
        # Identity is independent of short/full URL spelling and repeated times.
        source_digest = digest([[cue.second, cue.text] for cue in source.cues])
        selected = source.scoped(interval)
        selected_ids = {id(cue) for cue in selected.cues}
        groups: list[tuple[EvidenceCue, ...]] = []
        parts: list[EvidenceCue] = []
        buffer: list[EvidenceCue] = []
        size = 0
        for ordinal, cue in enumerate(source.cues):
            if id(cue) not in selected_ids:
                continue
            for fragment, offset in enumerate(range(0, len(cue.text), 500)):
                part = EvidenceCue(
                    f"cue_{ordinal}_{fragment}", cue.second, cue.text[offset : offset + 500]
                )
                parts.append(part)
        for part in _paragraphs(parts):
            cost = len(part.text) + 80
            if buffer and size + cost > CHUNK_CHAR_BUDGET:
                groups.append(tuple(buffer))
                buffer, size = [], 0
            buffer.append(part)
            size += cost
        if buffer:
            groups.append(tuple(buffer))
        if not groups or len(groups) > MAX_CHUNKS:
            raise VideoSummaryFailure("invalid")
        return cls(
            source_digest,
            tuple(EvidenceChunk(i, source_digest, cues) for i, cues in enumerate(groups)),
        )


@dataclass(frozen=True, slots=True, repr=False)
class SupportingEvidence:
    cue_ids: tuple[str, ...]
    quote: str
    context: str
    start: float
    end: float
    reference_normalized: bool = False
    source_cue_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, repr=False)
class NotesPoint:
    block_id: str
    text: str
    evidence: tuple[SupportingEvidence, ...]


@dataclass(frozen=True, slots=True, repr=False)
class NotesSection:
    block_id: str
    title: str
    points: tuple[NotesPoint, ...]


@dataclass(frozen=True, slots=True, repr=False)
class VideoNotesDraft:
    source_digest: str
    chunk_index: int
    start: float
    end: float
    sections: tuple[NotesSection, ...]

    def payload(self) -> dict:
        return {
            "source_digest": self.source_digest,
            "chunk_index": self.chunk_index,
            "start": self.start,
            "end": self.end,
            "sections": [
                {
                    "block_id": section.block_id,
                    "title": section.title,
                    "points": [
                        {
                            "block_id": point.block_id,
                            "text": point.text,
                            "evidence": [
                                {
                                    "cue_ids": list(e.cue_ids),
                                    "quote": e.quote,
                                    "context": e.context,
                                    "start": e.start,
                                    "end": e.end,
                                    "reference_normalized": e.reference_normalized,
                                    "source_cue_ids": list(e.source_cue_ids),
                                }
                                for e in point.evidence
                            ],
                        }
                        for point in section.points
                    ],
                }
                for section in self.sections
            ],
        }

    @property
    def draft_digest(self) -> str:
        return digest(self.payload())


def _object(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise NotesProtocolFailure("shape")
    return value


def _list(value: object, maximum: int, *, label: str = "collection") -> list:
    if label == "section_count" and isinstance(value, list):
        if not value:
            raise NotesProtocolFailure("sections_missing")
        if len(value) > maximum:
            raise NotesProtocolFailure("sections_overflow")
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise NotesProtocolFailure(label)
    return value


def _text(value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise NotesProtocolFailure("text")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise NotesProtocolFailure("text")
    return normalized(value)


def _support(value: object, chunk: EvidenceChunk) -> SupportingEvidence:
    raw = _object(value, {"cue_ids", "quote"})
    ids = _list(raw["cue_ids"], 4, label="cue_count")
    if not ids:
        raise NotesProtocolFailure("cue_count")
    positions = {cue.cue_id: i for i, cue in enumerate(chunk.cues)}
    if any(not isinstance(cid, str) or cid not in positions for cid in ids):
        raise NotesProtocolFailure("cue_id")
    offsets = [positions[cid] for cid in ids]
    ordered = offsets == list(range(offsets[0], offsets[0] + len(offsets)))
    cues = [chunk.cues[i] for i in offsets]
    quote = _text(raw["quote"], 10_000)
    context = normalized(" ".join(cue.text for cue in cues))
    if not ordered or quote not in context:
        # Source IDs are system-owned. Resolve only a unique literal quote in
        # this already scoped chunk; never guess from similarity or model text.
        # Invalid IDs were rejected above, and repeated source text is ambiguous.
        matches = [cue for cue in chunk.cues if quote in normalized(cue.text)]
        if len(matches) == 1:
            matched = matches[0]
            actual = normalized(matched.text)
            if len(quote) >= 12 or quote == actual:
                return SupportingEvidence(
                    (matched.cue_id,),
                    quote,
                    actual,
                    matched.second,
                    matched.end,
                    True,
                    matched.source_ids or (matched.cue_id,),
                )
        if not ordered:
            raise NotesProtocolFailure("cue_order")
    # Validate the model excerpt literally, but publish the whole trusted cue
    # context, so shortened evidence cannot hide negation or conditions.
    if quote not in context:
        elsewhere = any(quote in normalized(cue.text) for cue in chunk.cues)
        raise NotesProtocolFailure("quote_scope" if elsewhere else "quote")
    if len(quote) < 12 and quote != context:
        raise NotesProtocolFailure("quote")
    return SupportingEvidence(
        tuple(ids),
        quote,
        context,
        cues[0].second,
        cues[-1].end,
        False,
        tuple(cid for cue in cues for cid in (cue.source_ids or (cue.cue_id,))),
    )


def parse_draft(value: object, chunk: EvidenceChunk) -> VideoNotesDraft:
    raw = _object(value, {"sections"})
    sections = []
    referenced: set[str] = set()
    point_count = 0
    for si, item in enumerate(_list(raw["sections"], 8, label="section_count")):
        section = _object(item, {"title", "points"})
        points = []
        for pi, item in enumerate(_list(section["points"], 8, label="point_count")):
            point = _object(item, {"text", "evidence"})
            text = _text(point["text"], 300)
            support = tuple(
                _support(e, chunk) for e in _list(point["evidence"], 4, label="evidence_count")
            )
            _validate_claim_alignment(text, support)
            referenced.update(cid for e in support for cid in e.cue_ids)
            points.append(NotesPoint(f"k{chunk.index:03d}-s{si:02d}-p{pi:02d}", text, support))
            point_count += 1
        sections.append(
            NotesSection(
                f"k{chunk.index:03d}-s{si:02d}", _text(section["title"], 180), tuple(points)
            )
        )
    if point_count > 32:
        raise NotesProtocolFailure("point_limit")
    # Structural coverage is not semantic coverage. Require source anchors from
    # beginning/middle/end so a valid response cannot cite only the introduction.
    covered = {
        min(2, i * 3 // len(chunk.cues))
        for i, cue in enumerate(chunk.cues)
        if cue.cue_id in referenced
    }
    expected = {min(2, i * 3 // len(chunk.cues)) for i in range(len(chunk.cues))}
    if covered != expected:
        raise NotesProtocolFailure("coverage")
    return VideoNotesDraft(
        chunk.source_digest, chunk.index, chunk.start, chunk.end, _unique_points(sections)
    )


def _unique_points(sections: list[NotesSection]) -> tuple[NotesSection, ...]:
    """Remove exact repeated claims with identical provenance, never paraphrases."""
    seen = set()
    result = []
    for section in sections:
        points = []
        for point in section.points:
            key = (
                normalized(point.text),
                tuple(sorted((e.cue_ids, normalized(e.quote)) for e in point.evidence)),
            )
            if key not in seen:
                seen.add(key)
                points.append(point)
        if points:
            result.append(NotesSection(section.block_id, section.title, tuple(points)))
    return tuple(result)


def parse_grouped_draft(value: object, chunk: EvidenceChunk) -> VideoNotesDraft:
    """Require evidence from each source scope, not a model coverage assertion."""
    groups = chunk.coverage_groups()
    raw = _object(value, set(groups))
    sections = []
    for name, cues in groups.items():
        scope = EvidenceChunk(chunk.index, chunk.source_digest, cues)
        group = raw[name]
        if not isinstance(group, dict) or "primary" not in group:
            raise NotesProtocolFailure("sections_missing")
        if set(group) != {"primary"}:
            raise NotesProtocolFailure("sections_overflow")
        items = [group["primary"]]
        for item in items:
            section = _object(item, {"title", "points"})
            for point in _list(section["points"], 3, label="point_count"):
                point = _object(point, {"text", "evidence"})
                for support in _list(point["evidence"], 4, label="evidence_count"):
                    _support(support, scope)
        sections.extend(items)
    return parse_draft({"sections": sections}, chunk)


def plain_markdown(text: str) -> str:
    # Only the trusted renderer can create links or structural Markdown.
    return re.sub(r"([\\`*_{}\[\]()#+.!|<>])", r"\\\1", normalized(text))
