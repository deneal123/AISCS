"""Модельный double не выполняет инструменты и не принимает selector за tool call."""

import json

import httpx
import pytest

from scripts.harness_live.model_transport import ScriptedProvider


@pytest.mark.parametrize("scenario", ["read_change", "question_change"])
def test_read_change_selector_returns_a_text_decision_not_an_unoffered_function(
    monkeypatch, scenario
):
    monkeypatch.setenv("HARNESS_ACCEPTANCE_SCENARIO", scenario)
    monkeypatch.setenv("HARNESS_ACCEPTANCE_PROVIDER", "gigachat")
    model = ScriptedProvider()
    result = model.completion(
        httpx.Request(
            "POST",
            "https://example.invalid",
            json={
                "model": model.model,
                "messages": [
                    {"role": "system", "content": "Ты выбираешь, какие ИНСТРУМЕНТЫ показать."}
                ],
            },
        )
    ).json()
    message = result["choices"][0]["message"]
    assert json.loads(message["content"]) == {
        "tools": ["ide_read_file"],
        "preferred_tool": "ide_read_file",
    }
    assert "tool_calls" not in message and "function_call" not in message
    assert model.tool_names == []


def test_parked_read_model_decisions_require_second_read_before_finish():
    from scripts.harness_live.question_change import STEPS, next_step

    completed = []
    for expected in STEPS:
        assert next_step(completed) == expected
        completed.append(expected[0])
    assert completed == ["ide_read_file", "ask_user_question", "ide_read_file", "ide_finish_task"]
    assert next_step(completed) is None
    with pytest.raises(ValueError, match="acceptance_unexpected_question_history"):
        next_step(["ide_read_file", "ask_user_question", "ide_finish_task"])
