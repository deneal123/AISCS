"""Authenticated explicit reply/cancel, closed bodies and production error envelope."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from service.services.chat.domain.human_questions.contracts import HumanQuestionError, QuestionScope
from service.services.chat.presentation.routers.chat_api import human_question_routes as api
from service.shared.presentation.handlers.exceptions_handlers import setup_exception_handlers
from service.shared.repositories.exceptions import RepositoryOperationalError
from service.shared.security.auth_checker import check_auth


@pytest.fixture
def fixture():
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(api.router, prefix="/api/chats")
    scope = QuestionScope(uuid4(), uuid4(), uuid4())
    question_id = uuid4()
    service = SimpleNamespace(
        **{
            name: AsyncMock(return_value={"state": "pending"})
            for name in ("read", "answer", "cancel", "read_cost", "decide_cost")
        }
    )
    app.dependency_overrides[api.get_questions] = lambda: service
    path = f"/api/chats/{scope.thread_id}/runs/{scope.source_job_id}/questions/{question_id}"
    body = {
        "intent_id": str(uuid4()),
        "answer": {"text": "Use Python"},
        "surface": "ide",
        "ide_context": {"repository_id": str(uuid4()), "generation": "a" * 64},
    }
    return SimpleNamespace(**locals())


def sign_in(f):
    f.app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=f.scope.user_id)


def test_question_endpoints_require_auth_before_work(fixture):
    f = fixture
    with TestClient(f.app) as client:
        for method, suffix, body in [
            ("GET", "", None),
            ("POST", "/answer", f.body),
            ("POST", "/cancel", {}),
            ("GET", "/cost", None),
            ("POST", "/cost", {"offer_id": str(uuid4()), "decision": "accept"}),
        ]:
            assert client.request(method, f.path + suffix, json=body).status_code == 401
    for method in vars(f.service).values():
        method.assert_not_awaited()


def test_read_reply_cancel_are_separate_owned_and_private(fixture):
    f = fixture
    sign_in(f)
    with TestClient(f.app) as client:
        result = client.get(f.path)
        assert result.status_code == 200
        assert result.headers["cache-control"] == "private, no-store"
        f.service.answer.assert_not_awaited()
        f.service.cancel.assert_not_awaited()
        assert client.post(f.path + "/answer", json=f.body).status_code == 200
        assert client.post(f.path + "/cancel", json={}).status_code == 200
    f.service.read.assert_awaited_once_with(f.scope, f.question_id)
    f.service.cancel.assert_awaited_once_with(f.scope, f.question_id)
    args = f.service.answer.await_args.args
    assert args[:2] == (f.scope, f.question_id)
    assert str(args[2].intent_id) == f.body["intent_id"]


@pytest.mark.parametrize("state", ["pending", "expired", "accepted", "declined", "not_required"])
def test_cost_reads_are_passive_and_only_ready_decisions_wake_the_same_child(
    fixture, monkeypatch, state
):
    from unittest.mock import Mock

    f = fixture
    sign_in(f)
    offer = uuid4()
    wake = Mock()
    monkeypatch.setattr(api, "trigger_human_question_dispatch", wake)
    f.service.decide_cost.return_value = {"state": state}
    with TestClient(f.app) as client:
        read = client.get(f.path + "/cost")
        assert read.status_code == 200 and read.headers["cache-control"] == "private, no-store"
        wake.assert_not_called()
        f.service.decide_cost.assert_not_awaited()
        result = client.post(f.path + "/cost", json={"offer_id": str(offer), "decision": "accept"})
        assert result.status_code == 200
    f.service.read_cost.assert_awaited_once_with(f.scope, f.question_id)
    f.service.decide_cost.assert_awaited_once_with(f.scope, f.question_id, offer, "accept")
    assert wake.call_count == int(state in {"accepted", "not_required"})


@pytest.mark.parametrize(
    "extra", ["user_id", "estimated_credits", "resume_job_id", "confirm_expensive_run", "binding"]
)
def test_cost_decision_body_cannot_override_authority(fixture, extra):
    f = fixture
    sign_in(f)
    with TestClient(f.app) as client:
        body = {"offer_id": str(uuid4()), "decision": "accept", extra: "PRIVATE"}
        assert client.post(f.path + "/cost", json=body).status_code == 422
    f.service.decide_cost.assert_not_awaited()


@pytest.mark.parametrize("state", ["pending", "accepted", "cancelled", "expired"])
def test_only_explicit_accepted_reply_wakes_the_outbox_after_response(fixture, monkeypatch, state):
    from unittest.mock import Mock

    f = fixture
    sign_in(f)
    wake = Mock()
    monkeypatch.setattr(api, "trigger_human_question_dispatch", wake)
    with TestClient(f.app) as client:
        client.get(f.path)
        client.post(f.path + "/cancel", json={})
        wake.assert_not_called()
        f.service.answer.return_value = {"state": state}
        assert client.post(f.path + "/answer", json=f.body).status_code == 200
    assert wake.call_count == int(state == "accepted")


@pytest.mark.parametrize("field", ["user_id", "continuation", "workspace_ref", "token"])
def test_reply_rejects_private_or_unknown_fields(fixture, field):
    f = fixture
    sign_in(f)
    f.body[field] = "untrusted-private-marker"
    with TestClient(f.app) as client:
        assert client.post(f.path + "/answer", json=f.body).status_code == 422
    f.service.answer.assert_not_awaited()


@pytest.mark.parametrize("case", ["both", "neither", "zero_intent", "private_target", "answer"])
def test_reply_rejects_ambiguous_scope_or_open_nested_body(fixture, case):
    f = fixture
    sign_in(f)
    if case == "both":
        f.body["document_context"] = {"path": "documents/default", "expected_revision": "rev"}
    elif case == "neither":
        f.body.pop("ide_context")
    elif case == "zero_intent":
        f.body["intent_id"] = str(UUID(int=0))
    elif case == "private_target":
        f.body["ide_context"]["token"] = "private-marker"
    else:
        f.body["answer"]["tool_call_id"] = "private-marker"
    with TestClient(f.app) as client:
        assert client.post(f.path + "/answer", json=f.body).status_code == 422
        assert (
            client.post(f.path + "/cancel", json={"resume_job_id": str(uuid4())}).status_code == 422
        )
    f.service.answer.assert_not_awaited()
    f.service.cancel.assert_not_awaited()


@pytest.mark.parametrize(
    "error,status,code",
    [
        (HumanQuestionError("human_question_not_found"), 404, "human_question_not_found"),
        (HumanQuestionError("human_question_conflict"), 409, "human_question_conflict"),
        (
            HumanQuestionError("human_question_binding_changed"),
            409,
            "human_question_binding_changed",
        ),
        (RepositoryOperationalError("private-marker"), 503, "human_question_status_unknown"),
        (HTTPException(409, "source_changed"), 409, "source_changed"),
        (HTTPException(500, "private-marker"), 503, "human_question_unavailable"),
    ],
)
def test_bounded_errors_keep_explicit_code_and_no_private_details(fixture, error, status, code):
    f = fixture
    sign_in(f)
    f.service.answer.side_effect = error
    with TestClient(f.app) as client:
        response = client.post(f.path + "/answer", json=f.body)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private-marker" not in response.text
    assert response.headers["cache-control"] == "private, no-store"


def test_default_gate_refuses_before_repository_lookup(fixture, monkeypatch):
    f = fixture
    monkeypatch.setattr(api.config.human_questions, "enabled", False)
    monkeypatch.setattr(api, "get_app_container", lambda _: pytest.fail("container read"))
    with pytest.raises(HTTPException) as error:
        api.get_questions(None, SimpleNamespace(user_id=f.scope.user_id), object(), object())
    assert error.value.status_code == 503
