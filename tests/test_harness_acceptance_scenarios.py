"""Acceptance scripts must advance by history, including repeated checks and reads."""

import hashlib

import pytest

from scripts.harness_live.scenarios import BROKEN_SCRIPT, SCRIPT, next_step, steps


@pytest.mark.parametrize("scenario,rounds", [("hello", 5), ("repair", 9), ("stop", 5)])
def test_scenario_advances_by_exact_history_and_never_restarts(scenario, rounds):
    history = []
    for expected in steps(scenario):
        assert next_step(scenario, history) == expected
        history.append(expected[0])
    assert len(history) == rounds
    assert next_step(scenario, history) is None
    with pytest.raises(ValueError, match="unexpected_tool_history"):
        next_step(scenario, history + ["ide_write_file"])


def test_repair_rereads_failed_sources_and_keeps_the_original_verification_recipe():
    plan = steps("repair")
    assert plan[1][1]["content"] == BROKEN_SCRIPT
    assert plan[4][0] == "ide_read_file"
    assert plan[5] == (
        "ide_edit_file",
        {
            "path": "hello_world.py",
            "old": BROKEN_SCRIPT,
            "new": SCRIPT,
            "base_digest": hashlib.sha256(BROKEN_SCRIPT.encode()).hexdigest(),
        },
    )
    original, repeated = plan[3][1], plan[7][1]
    assert {
        key: original[key] for key in ("profile", "target", "expected_stdout", "criterion_id")
    } == {key: repeated[key] for key in ("profile", "target", "expected_stdout", "criterion_id")}
    assert original["timeout_sec"] != repeated["timeout_sec"]
    assert original["command"] is None and "command" not in repeated


@pytest.mark.parametrize("history", [["ide_write_file"], ["ide_list_files", "ide_finish_task"]])
def test_unexpected_history_does_not_mask_a_tool_failure(history):
    with pytest.raises(ValueError, match="unexpected_tool_history"):
        next_step("repair", history)
