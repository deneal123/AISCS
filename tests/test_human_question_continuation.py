import copy
import json

import pytest

from service.services.chat.domain.human_questions.contracts import (
    HumanQuestionError,
    QuestionPrompt,
    freeze_question_continuation,
    parse_resumed_question_continuation,
    resume_question_continuation,
)


def transcript():
    prompt = QuestionPrompt.parse({"prompt": "Что добавить?", "choices": []})
    return prompt, {
        "model": "test-model",
        "tool_call_id": "question",
        "messages": [
            {"role": "user", "content": "Добавь README и уточни структуру."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "write",
                        "type": "function",
                        "function": {
                            "name": "ide_write_file",
                            "arguments": '{"content":"PRIVATE-SOURCE"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "write", "content": '{"written":true}'},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "question",
                        "type": "function",
                        "function": {
                            "name": "ask_user_question",
                            "arguments": json.dumps(prompt.payload()),
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "question", "content": '{"awaiting_user":true}'},
        ],
    }


def test_resume_changes_only_the_pending_tool_result_and_keeps_completed_writes():
    prompt, raw = transcript()
    before = copy.deepcopy(raw)
    frozen = freeze_question_continuation(raw, prompt)
    result = resume_question_continuation(raw, prompt, {"choice_id": None, "text": "src и tests"})
    assert raw == before and json.loads(frozen) == before
    assert result["messages"][:-1] == raw["messages"][:-1]
    assert json.loads(result["messages"][-1]["content"]) == {
        "answer": {"choice_id": None, "text": "src и tests"}
    }
    assert [message["role"] for message in result["messages"]].count("user") == 1
    assert result["messages"][2]["content"] == '{"written":true}'
    assert parse_resumed_question_continuation(result) == result


@pytest.mark.parametrize(
    "fault",
    [
        "extra-capability",
        "unbalanced",
        "other-tool",
        "other-prompt",
        "wrong-id",
        "numeric-sentinel",
        "extra-message-field",
        "multimodal",
        "invalid-role",
        "oversize",
    ],
)
def test_private_transcript_rejects_incomplete_or_capability_bearing_envelopes(fault):
    prompt, raw = transcript()
    if fault == "extra-capability":
        raw["workspace_ref"] = {"token": "PRIVATE"}
    if fault == "unbalanced":
        raw["messages"].pop(2)
    if fault == "other-tool":
        raw["messages"][-2]["tool_calls"][0]["function"]["name"] = "ide_write_file"
    if fault == "other-prompt":
        raw["messages"][-2]["tool_calls"][0]["function"]["arguments"] = (
            '{"prompt":"Другой вопрос?","choices":[]}'
        )
    if fault == "wrong-id":
        raw["messages"][-1]["tool_call_id"] = "foreign"
    if fault == "numeric-sentinel":
        raw["messages"][-1]["content"] = '{"awaiting_user":1}'
    if fault == "extra-message-field":
        raw["messages"][0]["token"] = "PRIVATE"
    if fault == "multimodal":
        raw["messages"][0]["content"] = [{"image_url": "PRIVATE"}]
    if fault == "invalid-role":
        raw["messages"][0]["role"] = []
    if fault == "oversize":
        raw["messages"][0]["content"] = "x" * (1024 * 1024)
    with pytest.raises(HumanQuestionError):
        freeze_question_continuation(raw, prompt)
