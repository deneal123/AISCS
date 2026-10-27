"""Приёмка продолжения sealed-task после правки во время ожидания пользователя."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(os.getenv("HARNESS_QUESTION_CHANGE_LIVE") != "1", reason="Worker opt-in")
@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai"])
def test_user_edit_while_parked_requires_fresh_child_evidence_without_replay(provider):
    result = run_command_probe(
        agents=True, worker=True, scenario="question_change", provider=provider
    )
    assert result["parked_read_invalidated"] and result["child_reread_verified"]
