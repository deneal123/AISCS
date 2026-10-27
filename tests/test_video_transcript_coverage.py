from service.domain.tools.video_tool import MAX_CUES, _describe


def test_transcript_only_result_does_not_claim_visual_access():
    result = _describe({"transcript": [{"t_sec": 0, "text": "source"}], "frames": []})
    assert "Получена расшифровка ролика" in result
    assert "Просмотрен ролик" not in result


def test_clipped_transcript_cannot_be_presented_as_complete():
    result = _describe(
        {"transcript": [{"t_sec": i, "text": "source"} for i in range(MAX_CUES + 1)], "frames": []}
    )
    assert "Не называйте конспект полным" in result
