"""Extract current structured audio attachments, with legacy marker fallback."""

from __future__ import annotations

import json
import re
from pathlib import PurePath
from typing import Any

from .models import AudioTranscript, TranscriptBatch, TranscriptSegment, segments_from_iterable

_FILE_CONTEXT_MARKER = "## Контекст из загруженного файла:"
_FAILURE_MARKERS = (
    "транскрипция недоступна",
    "аудио загружено, но транскрипция недоступна",
    "аудио файл:",
    "аудио не распознано",
)


def split_legacy_input(text: str) -> tuple[str, str]:
    value = str(text or "")
    if _FILE_CONTEXT_MARKER not in value:
        return value.strip(), ""
    user_part, file_part = value.split(_FILE_CONTEXT_MARKER, 1)
    return user_part.strip(), file_part.strip()


def _safe_name(value: Any, index: int) -> str:
    name = PurePath(str(value or "")).name
    name = re.sub(r"[^\w .()\[\]-]+", "_", name, flags=re.UNICODE).strip(" ._")
    return name[:160] or f"audio-{index + 1}"


def _structured_content(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    value = content.strip()
    if not value.startswith("{"):
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _transcript_from_attachment(attachment: Any, index: int) -> AudioTranscript | None:
    kind = str(
        attachment.get("kind") if isinstance(attachment, dict) else getattr(attachment, "kind", "")
    ).lower()
    if kind != "audio":
        return None
    name = (
        attachment.get("name") if isinstance(attachment, dict) else getattr(attachment, "name", "")
    )
    content = (
        attachment.get("content")
        if isinstance(attachment, dict)
        else getattr(attachment, "content", "")
    )
    structured = _structured_content(content)
    if structured is not None:
        raw_segments = structured.get("segments")
        if isinstance(raw_segments, list):
            segments = segments_from_iterable(raw_segments)
        else:
            segments = segments_from_iterable([structured.get("text") or ""])
        language = str(structured.get("language") or "").strip()[:32] or None
    else:
        segments = segments_from_iterable([content])
        language = None
    if not segments:
        return None
    return AudioTranscript(
        attachment_index=index,
        safe_name=_safe_name(name, index),
        segments=segments,
        language=language,
    )


def _legacy_transcript(user_input: str, context: Any) -> tuple[str, AudioTranscript | None]:
    user_task, file_context = split_legacy_input(user_input)
    if not file_context:
        _, file_context = split_legacy_input(getattr(context, "system_context", None) or "")
    value = re.sub(r"\n{3,}", "\n\n", file_context).strip()
    if not value or any(marker in value.lower() for marker in _FAILURE_MARKERS):
        return user_task, None
    return user_task, AudioTranscript(
        attachment_index=0,
        safe_name="audio-1",
        segments=(TranscriptSegment(value),),
    )


def extract_audio_batch(user_input: str, context: Any) -> tuple[str, TranscriptBatch]:
    """Prefer explicit current attachments and never parse source URLs."""

    current = list(getattr(context, "current_attachments", None) or [])
    transcripts = [
        transcript
        for index, attachment in enumerate(current)
        if (transcript := _transcript_from_attachment(attachment, index)) is not None
    ]
    task, _legacy = split_legacy_input(user_input)
    if transcripts:
        return task, TranscriptBatch(transcripts=transcripts, legacy_fallback=False)
    task, legacy = _legacy_transcript(user_input, context)
    return task, TranscriptBatch(
        transcripts=[legacy] if legacy is not None else [],
        legacy_fallback=legacy is not None,
    )


__all__ = ["extract_audio_batch", "split_legacy_input"]
