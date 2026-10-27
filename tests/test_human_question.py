import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from service.services.chat.domain.human_questions.contracts import (
    HumanQuestionError,
    QuestionAnswer,
    QuestionChoice,
    QuestionPause,
    QuestionPrompt,
    QuestionScope,
    freeze_continuation,
)
from service.services.chat.persistence.human_questions.repository import public_question


def prompt():
    return QuestionPrompt.parse(
        {
            "prompt": "Какой формат нужен?",
            "choices": [
                {"id": "document", "label": "Документ"},
                {"id": "slides", "label": "Презентация"},
            ],
        }
    )


def pause():
    return QuestionPause(
        QuestionScope(uuid4(), uuid4(), uuid4()),
        uuid4(),
        uuid4(),
        "ide",
        uuid4(),
        "a" * 64,
        prompt(),
        time.time() + 60,
        freeze_continuation({"messages": [{"role": "tool", "content": "PRIVATE"}]}),
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"prompt": "x", "choices": [], "token": "x"},
        {"prompt": "", "choices": []},
        {"prompt": " x", "choices": []},
        {"prompt": "x\n", "choices": []},
        {"prompt": "x\x00y", "choices": []},
        {"prompt": "x" * 1001, "choices": []},
        {"prompt": True, "choices": []},
        {"prompt": "x", "choices": [{"id": "one", "label": "One"}]},
        {
            "prompt": "x",
            "choices": [{"id": "same", "label": "One"}, {"id": "same", "label": "Two"}],
        },
        {"prompt": "x", "choices": [{"id": "One", "label": "One"}, {"id": "two", "label": "Two"}]},
    ],
)
def test_invalid_model_questions_are_closed(value):
    with pytest.raises(HumanQuestionError, match="^human_question_invalid$"):
        QuestionPrompt.parse(value)


def test_question_supports_free_text_without_forcing_an_option():
    free = QuestionPrompt.parse({"prompt": "Что добавить?", "choices": []})
    value = {"choice_id": None, "text": "Своё описание\nс деталями"}
    assert QuestionAnswer.parse(value, free).payload() == value
    selected = {"choice_id": "slides", "text": "Для школьников"}
    assert QuestionAnswer.parse(selected, prompt()).payload() == selected


@pytest.mark.parametrize(
    "value",
    [
        {},
        None,
        {"choice_id": None, "text": None},
        {"choice_id": "unknown", "text": None},
        {"choice_id": True, "text": None},
        {"choice_id": None, "text": " "},
        {"choice_id": None, "text": "x" * 4001},
        {"choice_id": None, "text": "x\x00y"},
        {"choice_id": "slides", "text": None, "job_id": "other"},
    ],
)
def test_answer_rejects_unknown_options_controls_and_extra_authority(value):
    with pytest.raises(HumanQuestionError):
        QuestionAnswer.parse(value, prompt())


def test_direct_prompt_construction_cannot_bypass_validation():
    with pytest.raises(HumanQuestionError):
        QuestionPrompt("x", ("not-a-choice", "not-a-choice"))
    with pytest.raises(HumanQuestionError):
        QuestionChoice("bad key", "Label")


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": True},
        {"expires_at": float("nan")},
        {"expires_at": -1},
        {"surface": "chat"},
        {"project_id": "foreign"},
        {"continuation_json": "[]"},
        {"continuation_json": '{"b":2,"a":1}'},
        {"revision": ""},
    ],
)
def test_private_pause_is_bounded_and_frozen(changes):
    with pytest.raises(HumanQuestionError):
        replace(pause(), **changes)


def test_continuation_is_a_private_exact_copy_and_controls_the_intent_digest():
    private = {"messages": [{"role": "assistant", "content": "PRIVATE"}]}
    frozen = freeze_continuation(private)
    private["messages"].clear()
    item = replace(pause(), continuation_json=frozen)
    assert json.loads(item.continuation_json)["messages"]
    assert "PRIVATE" not in repr(item)
    assert item.resume_job_id == item.resume_job_id
    assert item.params()["digest"] != replace(item, continuation_json="{}").params()["digest"]
    with pytest.raises(HumanQuestionError):
        freeze_continuation({"text": "я" * 524288})


def test_public_projection_never_exposes_private_resume_state_or_answer():
    item = pause()
    row = {
        **item.params(),
        "source_job_id": item.scope.source_job_id,
        "prompt": item.prompt.payload(),
        "state": "pending",
        "alive": False,
        "expires_at": datetime.now(UTC),
        "resume_job_id": None,
        "answer": {"text": "PRIVATE-ANSWER"},
    }
    view = public_question(row)
    assert view["state"] == "expired"
    assert set(view) == {
        "question_id",
        "source_job_id",
        "surface",
        "project_id",
        "prompt",
        "choices",
        "state",
        "expires_at",
        "resume_job_id",
    }
    assert "PRIVATE" not in json.dumps(view)
