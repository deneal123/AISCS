"""Read-only corpus различает ясную задачу, анализ и существенную неизвестность."""

from types import SimpleNamespace

import pytest

from local_llm.scripts.acceptance.admission import (
    CASES,
    case_set,
    concise_messages,
    guided_messages,
    matches,
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


def test_holdouts_are_explicit_and_do_not_expand_default_budget():
    assert len(case_set("basic")) == 3
    extended = case_set("extended")
    assert len(extended) == 5
    example = guided_messages(SimpleNamespace(goal="проверка", actions=("read",)))[0]["content"]
    assert "subtract.py" not in example and "emit_a.py" not in example
    with pytest.raises(ValueError, match="admission_suite_invalid"):
        case_set("unknown")


def test_multi_file_control_rejects_omitted_or_extra_artifacts():
    case = case_set("extended")[-1]
    proposal = SimpleNamespace(
        kind="change",
        needs_clarification=False,
        criteria=[
            SimpleNamespace(kind="file", target="emit_a.py"),
            SimpleNamespace(kind="file", target="emit_b.py"),
        ],
    )
    assert matches(proposal, case)
    proposal.criteria.pop()
    assert not matches(proposal, case)
    proposal.criteria.append(SimpleNamespace(kind="file", target="example.py"))
    assert not matches(proposal, case)


def test_workflow_example_is_opt_in_not_a_change_to_historical_guided_profile():
    admission = SimpleNamespace(goal="проверка", actions=("read",))
    original = guided_messages(admission)[0]["content"]
    experimental = selected_builders("workflow_guided", object())[0][1](admission)[0]["content"]
    assert "worker.py" not in original and "worker.py" in experimental


def test_duplicate_result_is_not_a_successful_single_file_contract():
    case = CASES[0]
    criterion = SimpleNamespace(kind="file", target=case["target"])
    proposal = SimpleNamespace(kind="change", needs_clarification=False, criteria=[criterion])
    assert matches(proposal, case)
    proposal.criteria.append(criterion)
    assert not matches(proposal, case)
