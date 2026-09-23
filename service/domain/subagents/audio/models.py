"""Internal transcript model independent from Whisper and upload transports."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    text: str
    start_sec: float | None = None
    end_sec: float | None = None
    speaker: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", str(self.text or "").strip())
        if self.start_sec is not None:
            object.__setattr__(self, "start_sec", max(0.0, float(self.start_sec)))
        if self.end_sec is not None:
            object.__setattr__(self, "end_sec", max(0.0, float(self.end_sec)))
        if (
            self.start_sec is not None
            and self.end_sec is not None
            and self.end_sec < self.start_sec
        ):
            object.__setattr__(self, "end_sec", self.start_sec)
        if self.speaker is not None:
            speaker = re.sub(r"\s+", " ", str(self.speaker)).strip()[:80]
            object.__setattr__(self, "speaker", speaker or None)

    def render(self, *, timestamps: bool, speakers: bool) -> str:
        prefix: list[str] = []
        if timestamps and self.start_sec is not None:
            start = _format_time(self.start_sec)
            end = _format_time(self.end_sec) if self.end_sec is not None else ""
            prefix.append(f"[{start}{f'–{end}' if end else ''}]")
        if speakers and self.speaker:
            prefix.append(f"{self.speaker}:")
        return " ".join([*prefix, self.text]).strip()


def _format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


@dataclass(frozen=True, slots=True)
class AudioTranscript:
    attachment_index: int
    safe_name: str
    segments: tuple[TranscriptSegment, ...]
    language: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(segment.text for segment in self.segments if segment.text).strip()

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def has_timestamps(self) -> bool:
        return any(segment.start_sec is not None for segment in self.segments)

    @property
    def has_speakers(self) -> bool:
        return any(segment.speaker for segment in self.segments)

    def render(self, *, timestamps: bool = True, speakers: bool = True) -> str:
        show_timestamps = timestamps and self.has_timestamps
        show_speakers = speakers and self.has_speakers
        return "\n".join(
            segment.render(timestamps=show_timestamps, speakers=show_speakers)
            for segment in self.segments
            if segment.text
        ).strip()


@dataclass(frozen=True, slots=True)
class TranscriptChunk:
    transcript_index: int
    chunk_index: int
    chunk_count: int
    text: str


@dataclass(slots=True)
class TranscriptBatch:
    transcripts: list[AudioTranscript] = field(default_factory=list)
    legacy_fallback: bool = False

    @property
    def total_chars(self) -> int:
        return sum(item.char_count for item in self.transcripts)

    @property
    def segment_count(self) -> int:
        return sum(len(item.segments) for item in self.transcripts)

    @property
    def empty(self) -> bool:
        return not any(item.text for item in self.transcripts)

    def render_full(self) -> str:
        sections: list[str] = []
        multiple = len(self.transcripts) > 1
        for index, transcript in enumerate(self.transcripts, 1):
            heading = (
                f"### Транскрипт {index}: {transcript.safe_name}"
                if multiple
                else "### Распознанный текст"
            )
            sections.append(f"{heading}\n\n{transcript.render()}")
        return "\n\n".join(sections)

    def chunks(self, max_chars: int = 12000) -> list[TranscriptChunk]:
        chunks: list[TranscriptChunk] = []
        for transcript_index, transcript in enumerate(self.transcripts):
            parts = split_transcript(transcript.render(), max_chars=max_chars)
            for chunk_index, text in enumerate(parts):
                chunks.append(
                    TranscriptChunk(
                        transcript_index=transcript_index,
                        chunk_index=chunk_index,
                        chunk_count=len(parts),
                        text=text,
                    )
                )
        return chunks


def split_transcript(text: str, *, max_chars: int = 12000) -> list[str]:
    """Split without dropping a character; prefer paragraph and sentence boundaries."""

    value = str(text or "").strip()
    if not value:
        return []
    limit = max(1000, int(max_chars))
    parts: list[str] = []
    cursor = 0
    while cursor < len(value):
        end = min(len(value), cursor + limit)
        if end < len(value):
            window = value[cursor:end]
            candidates = (
                window.rfind("\n\n", limit // 2),
                window.rfind("\n", limit // 2),
                max(window.rfind(". ", limit // 2), window.rfind("! ", limit // 2)),
                window.rfind("? ", limit // 2),
                window.rfind(" ", limit // 2),
            )
            split_at = max(candidates)
            if split_at > 0:
                end = cursor + split_at + 1
        part = value[cursor:end]
        if part:
            parts.append(part)
        cursor = end
    return parts


def segments_from_iterable(items: Iterable[Any]) -> tuple[TranscriptSegment, ...]:
    result: list[TranscriptSegment] = []
    for item in items:
        if isinstance(item, TranscriptSegment):
            segment = item
        elif isinstance(item, dict):
            segment = TranscriptSegment(
                text=str(item.get("text") or item.get("content") or ""),
                start_sec=item.get("start") or item.get("start_sec"),
                end_sec=item.get("end") or item.get("end_sec"),
                speaker=item.get("speaker"),
            )
        else:
            segment = TranscriptSegment(str(item or ""))
        if segment.text:
            result.append(segment)
    return tuple(result)


__all__ = [
    "AudioTranscript",
    "TranscriptBatch",
    "TranscriptChunk",
    "TranscriptSegment",
    "segments_from_iterable",
    "split_transcript",
]
