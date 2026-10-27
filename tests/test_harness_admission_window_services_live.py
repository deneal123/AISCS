"""Вопрос после двух model calls, подтверждённый ответ, тот же task и денежный журнал."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(
    os.getenv("HARNESS_ADMISSION_WINDOW_LIVE") != "1", reason="isolated question-window opt-in"
)
def test_question_after_admission_review_resumes_through_real_outbox_worker():
    result = run_command_probe(agents=True, worker=True, scenario="clarify", review_questions=True)
    assert result["reviewed_question_resume_verified"] and result["outbox_worker_resumed"]
    assert result["replay_and_restart_unchanged"] and result["command_effects"] == 1
