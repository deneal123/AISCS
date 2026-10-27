import pytest

from service.domain.video_summary.authoring import validate_notes
from service.domain.video_summary.pipeline import note_document
from service.domain.video_summary.source import (
    TranscriptCue,
    VideoSummaryFailure,
    VideoTranscript,
    requested_time_range,
)


@pytest.mark.parametrize(
    "text",
    [
        "Для создания качественного конспекта мне необходим сам контент видео.",
        "Пришлите расшифровку видео, чтобы я мог подготовить конспект.",
        "Текущая страница содержит лишь служебную информацию сервиса YouTube.",
        "I need the transcript to summarize the video.",
        "",
    ],
)
def test_source_refusal_is_not_a_finished_note(text):
    with pytest.raises(VideoSummaryFailure) as failure:
        validate_notes(text)
    assert failure.value.code == "protocol"


def test_real_notes_are_not_rejected():
    validate_notes("## 00:00 Введение\nАвтор определяет понятие и приводит пример.\n")


def test_explicit_range_selects_only_requested_cues():
    interval = requested_time_range("Сделай конспект с 02:00 до 04:00")
    assert interval == (120, 240)
    source = VideoTranscript(
        "https://youtu.be/example",
        "Video",
        600,
        (
            TranscriptCue(0, "before"),
            TranscriptCue(120, "selected"),
            TranscriptCue(239, "selected tail"),
            TranscriptCue(240, "after"),
        ),
    )
    assert [cue.text for cue in source.scoped(interval).cues] == ["selected", "selected tail"]
    assert source.scoped(None) is source
    note = note_document(
        source.scoped(interval), ["selected notes"], complete=True, interval=interval
    )
    assert "Выбранный диапазон: 02:00–04:00." in note
    assert "before" not in note and "after" not in note


@pytest.mark.parametrize(
    "prompt",
    [
        "Конспект с 04:00 до 02:00",
        "Конспект с 02:60 до 03:00",
    ],
)
def test_bad_explicit_ranges_are_rejected(prompt):
    with pytest.raises(VideoSummaryFailure):
        requested_time_range(prompt)
