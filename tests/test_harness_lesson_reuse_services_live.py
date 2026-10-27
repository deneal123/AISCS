"""Настоящие задания одного проекта; подмена только model HTTP."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(
    os.getenv("HARNESS_LESSON_REUSE_LIVE") != "1", reason="Изолированный reuse-стенд"
)
def test_new_task_reuses_verified_lesson_without_another_refinement_and_settles_once():
    outcome = run_command_probe(agents=True, worker=True, scenario="lesson_reuse")
    assert outcome["lesson_reuse_verified"] and outcome["skipped_new_refinement"]
    assert outcome["charges"] == 2 and outcome["mutations"] == 0
