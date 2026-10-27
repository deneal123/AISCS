"""Private worker material is loaded only from one accepted, owned child."""

import copy
import json
from uuid import uuid4, uuid5

import pytest

from service.services.chat.domain.documents.context import document_project_id
from service.services.chat.domain.human_questions.contracts import HumanQuestionError, QuestionScope
from service.services.chat.domain.human_questions.resume import (
    RESUME_CONTEXT_KEY,
    QuestionResume,
    resume_target,
)
from tests.test_human_question_continuation import transcript


def rows(surface="ide"):
    scope = QuestionScope(uuid4(), uuid4(), uuid4())
    question_id, project_id = uuid4(), uuid4()
    child_id = uuid5(question_id, "gpthub:human-question:resume:v1")
    target = {"repository_id": str(project_id), "generation": "a" * 64}
    if surface == "pdf":
        target = {"path": "documents/slides", "expected_revision": "a" * 64}
        project_id = type(project_id)(
            document_project_id(str(scope.user_id), str(scope.thread_id), target["path"])
        )
    prompt, raw = transcript()
    question = {
        "question_id": question_id,
        "user_id": scope.user_id,
        "thread_id": scope.thread_id,
        "source_job_id": scope.source_job_id,
        "state": "accepted",
        "resume_job_id": child_id,
        "surface": surface,
        "project_id": project_id,
        "revision": "a" * 64,
        "continuation": raw,
        "prompt": prompt.payload(),
        "answer": {"choice_id": None, "text": "PRIVATE-ANSWER"},
    }
    child = {
        "id": child_id,
        "status": "NEW",
        "payload": {
            "thread_id": str(scope.thread_id),
            RESUME_CONTEXT_KEY: target,
            "_human_question_parent_v1": {
                "question_id": str(question_id),
                "source_job_id": str(scope.source_job_id),
            },
        },
    }
    source = {"status": "SUCCESS", "payload": {"text": "PRIVATE-ORIGINAL-REQUEST"}}
    return scope, question, child, source


@pytest.mark.parametrize("surface", ["ide", "pdf"])
def test_accepted_child_material_replaces_only_the_answer_and_keeps_target_private(surface):
    args = rows(surface)
    before = copy.deepcopy(args)
    result = QuestionResume.from_owned_rows(*args)
    assert args == before
    assert result.resume_job_id == args[2]["id"]
    assert result.model == "test-model"
    messages = json.loads(result.messages_json)
    assert messages[:-1] == args[1]["continuation"]["messages"][:-1]
    assert json.loads(messages[-1]["content"]) == {"answer": args[1]["answer"]}
    assert "PRIVATE" not in repr(result)


@pytest.mark.parametrize(
    "fault",
    [
        "state",
        "terminal_child",
        "parent_status",
        "wrong_child",
        "wrong_parent",
        "wrong_thread",
        "wrong_owner",
        "wrong_source",
        "missing_target",
        "changed_revision",
        "foreign_project",
        "missing_text",
        "bad_answer",
        "incomplete_continuation",
    ],
)
def test_corrupt_or_foreign_resume_material_fails_closed(fault):
    scope, question, child, source = rows()
    if fault == "state":
        question["state"] = "pending"
    if fault == "terminal_child":
        child["status"] = "SUCCESS"
    if fault == "parent_status":
        source["status"] = "PROCESSING"
    if fault == "wrong_child":
        child["id"] = uuid4()
    if fault == "wrong_parent":
        child["payload"]["_human_question_parent_v1"]["source_job_id"] = str(uuid4())
    if fault == "wrong_thread":
        question["thread_id"] = uuid4()
    if fault == "wrong_owner":
        question["user_id"] = uuid4()
    if fault == "wrong_source":
        question["source_job_id"] = uuid4()
    if fault == "missing_target":
        child["payload"].pop(RESUME_CONTEXT_KEY)
    if fault == "changed_revision":
        child["payload"][RESUME_CONTEXT_KEY]["generation"] = "b" * 64
    if fault == "foreign_project":
        child["payload"][RESUME_CONTEXT_KEY]["repository_id"] = str(uuid4())
    if fault == "missing_text":
        source["payload"].pop("text")
    if fault == "bad_answer":
        question["answer"]["choice_id"] = "foreign"
    if fault == "incomplete_continuation":
        question["continuation"]["messages"].pop(2)
    with pytest.raises(HumanQuestionError, match="human_question_unavailable"):
        QuestionResume.from_owned_rows(scope, question, child, source)


def test_pdf_resume_does_not_accept_another_path_or_revision():
    scope, question, child, _ = rows("pdf")
    target = child["payload"][RESUME_CONTEXT_KEY]
    for changed in (
        {**target, "path": "documents/other"},
        {**target, "expected_revision": "b" * 64},
    ):
        with pytest.raises(HumanQuestionError, match="human_question_binding_changed"):
            resume_target(scope, "pdf", question["project_id"], question["revision"], changed)
