"""Read-only corpus различает ясную задачу, анализ и существенную неизвестность."""

from types import SimpleNamespace

import pytest

from local_llm.scripts.acceptance.admission import (
    CASES,
    concise_messages,
    guided_messages,
    selected_builders,
)


def test_probe_contains_positive_and_genuine_clarification_controls():
    assert {case["clarify"] for case in CASES} == {True, False}
    assert {case["kind"] for case in CASES} == {"analysis", "change"}
    assert len({case["goal"] for case in CASES}) == len(CASES)


def test_candidate_preserves_goal_and_does_not_claim_completion():
    for case in CASES:
        messages = concise_messages(SimpleNamespace(goal=case["goal"], actions=("read",)))
        assert messages[-1]["content"] == "Запрос: " + case["goal"]
        assert "не подтверждай успех" in messages[0]["content"]
        assert "needs_clarification=true" in messages[0]["content"]
        assert "действия: read." in messages[0]["content"]
        assert all(message["role"] != "tool" for message in messages)


def test_guided_diagnostic_is_read_only_and_examples_are_not_executed_transcript():
    for case in CASES:
        messages = guided_messages(SimpleNamespace(goal=case["goal"], actions=("read",)))
        assert len(messages) == 2 and messages[-1]["content"] == "Запрос: " + case["goal"]
        assert "только примеры формы" in messages[0]["content"]
        assert "не относятся к текущему запросу" in messages[0]["content"]
        assert '"kind":"file"' in messages[0]["content"]
        assert "needs_clarification=true" in messages[0]["content"]
        assert all("tool_calls" not in message for message in messages)


@pytest.mark.parametrize(
    "profile,expected",
    [
        ("both", ["baseline", "concise"]),
        ("all", ["baseline", "concise", "guided"]),
        ("guided", ["guided"]),
    ],
)
def test_new_diagnostic_profile_does_not_expand_existing_both_budget(profile, expected):
    assert [name for name, _ in selected_builders(profile, object())] == expected


def test_unknown_profile_is_not_a_successful_empty_corpus():
    with pytest.raises(ValueError, match="admission_profile_invalid"):
        selected_builders("unknown", object())
