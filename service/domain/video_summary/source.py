"""Immutable source coverage and deterministic, non-lossy transcript partitioning."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

SOURCE_KEY = "video.transcript"
RESULT_KEY = "video.summary"
MAX_SOURCE_BYTES = 750_000
MAX_CHUNKS = 32


class VideoSummaryFailure(RuntimeError):
    def __init__(self, code: str = "internal") -> None:
        self.code = code
        super().__init__(code)


def video_request_kind(request: str) -> str | None:
    """Recognize explicit video transcript requests and complete video summaries."""
    if not isinstance(request, str) or not request.strip():
        return None
    transcript = re.search(
        r"(?:транскрипц\w*|транскрипт\w*|транскрибир\w*|расшифров\w*|"
        r"transcri(?:be|pt(?:ion)?|bing))",
        request,
        re.I,
    )
    summary = re.search(
        r"(?:конспект\w*|lecture\s+notes|detailed\s+(?:summary|notes))", request, re.I
    )
    if not transcript and not summary:
        return None
    # Other explicit document formats stay on their established, separately confirmed path.
    if re.search(r"\b(?:pdf|пдф|docx|pptx|latex|beamer)\b|презентац", request, re.I):
        return None
    return "transcript" if transcript else "summary"


def summary_video_url(request: str) -> str | None:
    """Only explicit transcript/notes requests with exactly one supported video URL qualify."""
    if video_request_kind(request) is None:
        return None
    urls = list(
        dict.fromkeys(
            url.rstrip(".,;!?)") for url in re.findall(r"https?://[^\s<>\]\"'()]+", request)
        )
    )
    if len(urls) != 1:
        return None
    url = urls[0].rstrip(".,;!?)")
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return url if host in {"youtu.be", "youtube.com", "vimeo.com", "rutube.ru"} else None


def timestamp(seconds: float) -> str:
    minutes, second = divmod(int(seconds), 60)
    return f"{minutes:02d}:{second:02d}"


def requested_time_range(request: str) -> tuple[int, int] | None:
    """Only explicit timestamp ranges qualify; never guess a range with an LLM."""
    match = re.search(
        r"(?:\bс|\bfrom)\s+(\d{1,3}:\d{2}(?::\d{2})?)\s+(?:до|по|to)\s+(\d{1,3}:\d{2}(?::\d{2})?)",
        request,
        re.I,
    )
    if match is None:
        return None
    values = []
    for raw in match.groups():
        parts = [int(part) for part in raw.split(":")]
        if any(part >= 60 for part in parts[1:]):
            raise VideoSummaryFailure("invalid")
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + part
        values.append(seconds)
    if values[1] <= values[0]:
        raise VideoSummaryFailure("invalid")
    return values[0], values[1]


@dataclass(frozen=True, slots=True)
class TranscriptCue:
    second: float
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class TranscriptChunk:
    index: int
    start: float
    end: float
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class VideoTranscript:
    url: str = field(repr=False)
    title: str = field(repr=False)
    duration: float
    cues: tuple[TranscriptCue, ...] = field(repr=False)
    truncated: bool = False
    has_frames: bool = False

    def scoped(self, interval: tuple[int, int] | None) -> VideoTranscript:
        if interval is None:
            return self
        start, end = interval
        if self.duration and end > self.duration:
            raise VideoSummaryFailure("invalid")
        cues = tuple(cue for cue in self.cues if start <= cue.second < end)
        if not cues:
            raise VideoSummaryFailure("invalid")
        return VideoTranscript(
            self.url, self.title, self.duration, cues, self.truncated, self.has_frames
        )

    @classmethod
    def from_response(cls, url: str, data: dict) -> VideoTranscript | None:
        raw = data.get("transcript")
        if raw is not None and not isinstance(raw, list):
            raise VideoSummaryFailure("invalid")
        if not raw:
            return None
        if len(raw) > 20_000:
            raise VideoSummaryFailure("invalid")
        if isinstance(data.get("duration_sec"), bool) or (
            "transcript_truncated" in data and type(data["transcript_truncated"]) is not bool
        ):
            raise VideoSummaryFailure("invalid")
        cues = []
        total = 0
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise VideoSummaryFailure("invalid")
            if isinstance(item.get("t_sec"), bool):
                raise VideoSummaryFailure("invalid")
            text = item["text"].strip()
            try:
                second = float(item.get("t_sec", 0))
            except (TypeError, ValueError, OverflowError):
                raise VideoSummaryFailure("invalid") from None
            if not text or not math.isfinite(second) or second < 0:
                raise VideoSummaryFailure("invalid")
            if cues and second < cues[-1].second:
                raise VideoSummaryFailure("invalid")
            try:
                total += len(text.encode("utf-8"))
            except UnicodeError:
                raise VideoSummaryFailure("invalid") from None
            if total > MAX_SOURCE_BYTES:
                raise VideoSummaryFailure("invalid")
            cues.append(TranscriptCue(second, text))
        try:
            duration = float(data.get("duration_sec") or 0)
        except (TypeError, ValueError, OverflowError):
            raise VideoSummaryFailure("invalid") from None
        if not math.isfinite(duration) or duration < 0:
            raise VideoSummaryFailure("invalid")
        # Providers can round the media duration down to whole seconds.
        if duration and cues[-1].second > duration + 1:
            raise VideoSummaryFailure("invalid")
        return cls(
            url,
            str(data.get("title") or "Видео")[:300],
            duration,
            tuple(cues),
            bool(data.get("transcript_truncated")),
            bool(data.get("frames")),
        )

    def markdown(self) -> str:
        lines = [f"# Расшифровка: {self.title}", f"Источник: {self.url}", ""]
        lines.extend(f"[{timestamp(c.second)}] {c.text}" for c in self.cues)
        return "\n".join(lines) + "\n"

    def chunks(self, max_chars: int = 10_000) -> tuple[TranscriptChunk, ...]:
        if not 100 <= max_chars <= 10_000:
            raise VideoSummaryFailure("invalid")
        chunks: list[TranscriptChunk] = []
        buffer: list[str] = []
        size = 0
        start = end = 0.0
        for cue in self.cues:
            for offset in range(0, len(cue.text), max_chars - 32):
                line = f"[{timestamp(cue.second)}] {cue.text[offset : offset + max_chars - 32]}"
                if buffer and size + len(line) + 1 > max_chars:
                    chunks.append(TranscriptChunk(len(chunks), start, end, "\n".join(buffer)))
                    buffer, size = [], 0
                if not buffer:
                    start = cue.second
                end = cue.second
                buffer.append(line)
                size += len(line) + 1
        if buffer:
            chunks.append(TranscriptChunk(len(chunks), start, end, "\n".join(buffer)))
        if len(chunks) > MAX_CHUNKS:
            raise VideoSummaryFailure("invalid")
        return tuple(chunks)


@dataclass(frozen=True, slots=True)
class VideoSummaryArtifact:
    path: str
    size: int
    sha256: str
    chunks: int

    @classmethod
    def for_content(cls, path: str, content: str, chunks: int) -> VideoSummaryArtifact:
        raw = content.encode("utf-8")
        return cls(path, len(raw), hashlib.sha256(raw).hexdigest(), chunks)
