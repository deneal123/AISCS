import pytest

from service.domain.video_summary.source import VideoSummaryFailure, VideoTranscript


@pytest.mark.parametrize("field", ["duration_sec", "t_sec"])
@pytest.mark.parametrize("value", [10**1000, -(10**1000)], ids=["positive", "negative"])
def test_overflow_is_a_bounded_source_failure(field, value):
    data = {"duration_sec": 20, "transcript": [{"t_sec": 2, "text": "speech"}]}
    if field == "duration_sec":
        data[field] = value
    else:
        data["transcript"][0][field] = value
    with pytest.raises(VideoSummaryFailure, match="^invalid$"):
        VideoTranscript.from_response("https://youtu.be/example", data)


def test_cue_outside_known_duration_is_rejected():
    with pytest.raises(VideoSummaryFailure, match="^invalid$"):
        VideoTranscript.from_response(
            "https://youtu.be/example",
            {"duration_sec": 20, "transcript": [{"t_sec": 22, "text": "speech"}]},
        )


@pytest.mark.parametrize("duration, second", [(20, 20.5), (0, 22), (20, 2)])
def test_rounding_tolerance_and_unknown_duration_remain_supported(duration, second):
    source = VideoTranscript.from_response(
        "https://youtu.be/example",
        {"duration_sec": duration, "transcript": [{"t_sec": second, "text": "speech"}]},
    )
    assert source is not None
    assert source.cues[0].second == second


@pytest.mark.parametrize("field", ["duration_sec", "t_sec"])
@pytest.mark.parametrize("value", [True, False])
def test_boolean_does_not_become_a_video_timestamp(field, value):
    data = {"duration_sec": 20, "transcript": [{"t_sec": 0, "text": "speech"}]}
    if field == "duration_sec":
        data[field] = value
    else:
        data["transcript"][0][field] = value
    with pytest.raises(VideoSummaryFailure, match="^invalid$"):
        VideoTranscript.from_response("https://youtu.be/example", data)


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_source_completeness_flag_is_not_coerced(value):
    data = {
        "duration_sec": 20,
        "transcript": [{"t_sec": 0, "text": "speech"}],
        "transcript_truncated": value,
    }
    with pytest.raises(VideoSummaryFailure, match="^invalid$"):
        VideoTranscript.from_response("https://youtu.be/example", data)


@pytest.mark.parametrize("truncated", [True, False])
def test_explicit_boolean_completeness_and_numeric_text_times_remain_valid(truncated):
    source = VideoTranscript.from_response(
        "https://youtu.be/example",
        {
            "duration_sec": "20",
            "transcript": [{"t_sec": "2.5", "text": "speech"}],
            "transcript_truncated": truncated,
        },
    )
    assert source is not None
    assert source.duration == 20
    assert source.cues[0].second == 2.5
    assert source.truncated is truncated
