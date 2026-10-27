"""Owned reply admission, live-target validation and passive/idempotent recovery."""

import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4, uuid5

import pytest

from service.services.chat.application.human_questions import service as module
from service.services.chat.domain.documents.context import document_project_id
from service.services.chat.domain.human_questions.contracts import (
    HumanQuestionError,
    QuestionRefusal,
    QuestionScope,
)
from service.services.chat.domain.human_questions.cost import QuestionCost
from service.services.chat.domain.human_questions.reply import QuestionReplyInput
from service.services.chat.domain.ide.edits import IdeEditError


@pytest.fixture
def fixture(monkeypatch):
    scope = QuestionScope(uuid4(), uuid4(), uuid4())
    question = {
        "question_id": str(uuid4()),
        "source_job_id": str(scope.source_job_id),
        "surface": "ide",
        "project_id": str(uuid4()),
        "prompt": "Which project structure?",
        "choices": [{"id": "small", "label": "Small"}, {"id": "full", "label": "Full"}],
        "state": "pending",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        "resume_job_id": None,
    }
    accepted = {**question, "state": "accepted", "resume_job_id": str(uuid4())}
    repository = SimpleNamespace(
        read=AsyncMock(return_value=question),
        answer=AsyncMock(return_value=accepted),
        cancel=AsyncMock(return_value={**question, "state": "cancelled"}),
    )
    ide = AsyncMock()
    document = AsyncMock()
    binding = {
        "workspace_id": "private-id",
        "user_id": str(scope.user_id),
        "expires_at": time.time() + 300,
    }
    read_binding = AsyncMock(return_value=("ready", binding))
    monkeypatch.setattr(module, "resolve_ide_target", ide)
    monkeypatch.setattr(module, "validate_document_context", document)
    monkeypatch.setattr(module.workspace_client, "read_binding_state", read_binding)
    service = module.HumanQuestionService(repository, object(), object())
    payload = {
        "intent_id": str(uuid4()),
        "surface": "ide",
        "ide_context": {"repository_id": question["project_id"], "generation": "a" * 64},
        "answer": {"choice_id": "small", "text": None},
    }
    return SimpleNamespace(**locals())


def pdf_selection(f):
    f.question["surface"] = "pdf"
    f.question["project_id"] = document_project_id(
        str(f.scope.user_id), str(f.scope.thread_id), "documents/default"
    )
    f.accepted.update(surface="pdf", project_id=f.question["project_id"])
    f.payload.update(
        surface="pdf",
        document_context={"path": "documents/default", "expected_revision": "revision-2"},
    )
    f.payload.pop("ide_context")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_answer_admission_quotes_the_owned_frame_before_creating_any_child(fixture, failure):
    import json

    from service.services.chat.domain.human_questions.resume import QuestionResume

    f = fixture
    target = f.payload["ide_context"]
    resumed = QuestionResume(
        uuid4(),
        f.scope.source_job_id,
        uuid4(),
        "ide",
        "saved-model",
        "PRIVATE",
        json.dumps(target),
        "[]",
    )
    quote = QuestionCost.quote(resumed, 100, required=True)
    f.repository.plan_answer = AsyncMock(return_value=resumed)
    f.service.budget = SimpleNamespace(quote=AsyncMock(return_value=quote))
    if failure:
        f.service.budget.quote.side_effect = RuntimeError("PRIVATE_PRICE_BODY")
    payload = QuestionReplyInput.model_validate(f.payload)
    if failure:
        with pytest.raises(HumanQuestionError, match="^human_question_unavailable$"):
            await f.service.answer(f.scope, uuid4(), payload)
        f.repository.answer.assert_not_awaited()
    else:
        await f.service.answer(f.scope, uuid4(), payload)
        assert f.repository.answer.call_args.kwargs["cost"] is quote
        f.service.budget.quote.assert_awaited_once_with(resumed, auto_approved=False)
    f.ide.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["expired_accept", "lost_refresh", "accepted_retry"])
async def test_cost_recovery_does_not_revalidate_or_price_a_committed_decision(fixture, case):
    f = fixture
    old = uuid4()
    view = {"offer_id": str(old), "state": "expired" if case == "expired_accept" else "accepted"}
    decision = "accept"
    if case == "lost_refresh":
        view.update(offer_id=str(uuid5(old, "refresh:v1")), state="pending")
        decision = "refresh"
    f.service.costs = SimpleNamespace(
        read=AsyncMock(return_value=view), decide=AsyncMock(return_value=view)
    )
    f.repository.load_resume = AsyncMock()
    f.service.budget = SimpleNamespace(quote=AsyncMock())
    assert await f.service.decide_cost(f.scope, uuid4(), old, decision) == view
    f.repository.load_resume.assert_not_awaited()
    f.service.budget.quote.assert_not_awaited()
    f.ide.assert_not_awaited()
    assert f.service.costs.decide.await_count == int(case == "accepted_retry")


@pytest.mark.asyncio
async def test_new_cost_consent_revalidates_the_owned_target_without_creating_another_job(fixture):
    import json

    from service.services.chat.domain.human_questions.resume import QuestionResume

    f = fixture
    f.question.update(state="accepted", resume_job_id=f.accepted["resume_job_id"])
    offer = uuid4()
    resumed = QuestionResume(
        uuid4(),
        f.scope.source_job_id,
        uuid4(),
        "ide",
        "model",
        "PRIVATE",
        json.dumps(f.payload["ide_context"]),
        "[]",
    )
    f.repository.load_resume = AsyncMock(return_value=resumed)
    f.service.costs = SimpleNamespace(
        read=AsyncMock(return_value={"offer_id": str(offer), "state": "pending"}),
        decide=AsyncMock(return_value={"state": "accepted"}),
    )
    result = await f.service.decide_cost(f.scope, uuid4(), offer, "accept")
    assert result["state"] == "accepted"
    f.ide.assert_awaited_once()
    f.repository.answer.assert_not_awaited()
    f.service.costs.decide.assert_awaited_once()


@pytest.mark.asyncio
async def test_passive_read_and_cancel_never_resolve_or_answer(fixture):
    f = fixture
    question_id = uuid4()
    assert await f.service.read(f.scope, question_id) == f.question
    assert (await f.service.cancel(f.scope, question_id))["state"] == "cancelled"
    f.repository.read.assert_awaited_once_with(f.scope, question_id)
    f.repository.cancel.assert_awaited_once_with(f.scope, question_id)
    f.repository.answer.assert_not_awaited()
    f.ide.assert_not_awaited()
    f.document.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["ide", "pdf"])
async def test_new_answer_validates_current_owned_target_before_admission(fixture, surface):
    f = fixture
    if surface == "pdf":
        pdf_selection(f)
    payload = QuestionReplyInput.model_validate(f.payload)
    result = await f.service.answer(f.scope, uuid4(), payload)
    assert result["resume_job_id"] == f.accepted["resume_job_id"]
    kwargs = f.repository.answer.await_args.kwargs
    assert str(kwargs["project_id"]) == f.question["project_id"]
    assert kwargs["intent_id"] == payload.intent_id
    assert kwargs["revision"] == ("a" * 64 if surface == "ide" else "revision-2")
    assert kwargs["answer"] == f.payload["answer"]
    if surface == "ide":
        f.ide.assert_awaited_once()
        f.document.assert_not_awaited()
    else:
        f.document.assert_awaited_once()
        assert f.read_binding.await_count == 2
        f.ide.assert_not_awaited()


@pytest.mark.asyncio
async def test_accepted_retry_uses_repository_replay_without_fresh_runtime(fixture):
    f = fixture
    f.repository.read.return_value = f.accepted
    f.repository.answer.return_value = QuestionRefusal("human_question_conflict")
    with pytest.raises(HumanQuestionError, match="human_question_conflict"):
        await f.service.answer(f.scope, uuid4(), QuestionReplyInput.model_validate(f.payload))
    f.ide.assert_not_awaited()
    f.document.assert_not_awaited()
    f.repository.answer.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["cancelled", "expired"])
async def test_terminal_unanswered_question_cannot_admit_child(fixture, state):
    f = fixture
    f.question["state"] = state
    assert (await f.service.answer(f.scope, uuid4(), QuestionReplyInput.model_validate(f.payload)))[
        "state"
    ] == state
    f.repository.answer.assert_not_awaited()
    f.ide.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "project", "answer", "runtime"])
async def test_invalid_or_stale_selection_does_not_admit_work(fixture, case):
    f = fixture
    code = "human_question_invalid"
    if case == "missing":
        f.repository.read.return_value = None
        code = "human_question_not_found"
    elif case == "project":
        f.payload["ide_context"]["repository_id"] = str(uuid4())
        code = "human_question_binding_changed"
    elif case == "answer":
        f.payload["answer"]["choice_id"] = "not-offered"
    else:
        f.ide.side_effect = IdeEditError("ide_generation_changed")
        code = "ide_generation_changed"
    with pytest.raises((HumanQuestionError, IdeEditError), match=code):
        await f.service.answer(f.scope, uuid4(), QuestionReplyInput.model_validate(f.payload))
    f.repository.answer.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unavailable", "foreign", "expired", "changed"])
async def test_pdf_answer_requires_still_live_owned_binding(fixture, case):
    f = fixture
    pdf_selection(f)
    status, binding = f.read_binding.return_value
    if case == "unavailable":
        f.read_binding.return_value = ("unavailable", None)
    elif case == "foreign":
        f.read_binding.return_value = (status, {**binding, "user_id": str(uuid4())})
    elif case == "expired":
        f.read_binding.return_value = (status, {**binding, "expires_at": time.time() - 1})
    else:
        f.read_binding.side_effect = [
            (status, binding),
            (status, {**binding, "workspace_id": "different"}),
        ]
    with pytest.raises(HumanQuestionError):
        await f.service.answer(f.scope, uuid4(), QuestionReplyInput.model_validate(f.payload))
    f.repository.answer.assert_not_awaited()
