import copy
import json
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.domain.human_questions.contracts import (
    HumanQuestionError,
    parse_public_question,
)
from service.services.chat.infrastructure.chat_worker.context.metadata import persistable_meta
from service.services.chat.infrastructure.chat_worker.continuation import (
    pause as human_question_pause,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.materialization.recovery import (
    MATERIALIZATION_KEY,
)
from service.services.chat.infrastructure.chat_worker.results import (
    early_resume as early_result_resume,
)
from service.services.chat.infrastructure.chat_worker.results.checkpoint import ACCEPTED_KEY


def fixture(surface="ide"):
    request = SimpleNamespace(job_id=str(uuid4()), thread_id=str(uuid4()), user_id=str(uuid4()))
    target = (
        {"repository_id": str(uuid4()), "generation": "a" * 64}
        if surface == "ide"
        else {"project_id": str(uuid4()), "expected_revision": "observed-before-write"}
    )
    ref = {
        "human_questions_enabled": True,
        "token": "PRIVATE-CAPABILITY",
        "workspace_id": "fixture-workspace",
        "expires_at": time.time() + 60,
        "ide_context" if surface == "ide" else "document_context": target,
    }
    state = SimpleNamespace(
        engine_env={"workspace_ref": ref},
        execution_attempt_id=str(uuid4()),
        reservation_id=None,
        reserved_estimate=0,
        accepted_captured=False,
    )
    prompt = {"prompt": "What should we add?", "choices": []}
    continuation = {
        "model": "synthetic",
        "tool_call_id": "q",
        "messages": [
            {"role": "user", "content": "PRIVATE-SOURCE"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "q",
                        "type": "function",
                        "function": {"name": "ask_user_question", "arguments": json.dumps(prompt)},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "q", "content": '{"awaiting_user":true}'},
        ],
    }
    result = {
        "reply": prompt["prompt"],
        "resolved_model": "synthetic",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "per_call_usage": [
            {
                "provider": "openai",
                "model": "synthetic",
                "call_id": "receipt",
                "prompt": 10,
                "completion": 5,
            }
        ],
        "metadata": {"execution_status": "waiting_user", "awaiting_user": True},
        human_question_pause.PAUSE_KEY: {
            "prompt": prompt,
            "continuation": continuation,
            "workspace_revision": "observed-after-write" if surface == "pdf" else None,
        },
    }
    return request, state, result


def view(pause):
    return {
        "question_id": str(pause.question_id),
        "source_job_id": str(pause.scope.source_job_id),
        "surface": pause.surface,
        "project_id": str(pause.project_id),
        **pause.prompt.payload(),
        "expires_at": datetime.fromtimestamp(pause.expires_at, UTC).isoformat(),
        "state": "pending",
        "resume_job_id": None,
    }


@pytest.mark.parametrize("surface", ["ide", "pdf"])
def test_private_pause_binds_to_server_target_and_latest_observed_revision(surface):
    request, state, result = fixture(surface)
    pause = human_question_pause.prepare_question(request, state, result, result["reply"])
    assert pause.surface == surface
    assert pause.revision == ("a" * 64 if surface == "ide" else "observed-after-write")
    assert "PRIVATE-CAPABILITY" not in pause.continuation_json
    assert "PRIVATE-SOURCE" in pause.continuation_json
    assert human_question_pause.prepare_question(request, state, result, result["reply"]) == pause


@pytest.mark.parametrize(
    "fault",
    [
        "no-capability",
        "numeric-capability",
        "no-private",
        "extra-private",
        "wrong-prompt",
        "wrong-model",
        "bad-transcript",
        "ambiguous-target",
    ],
)
def test_unrequested_or_unbound_question_cannot_become_a_public_wait(fault):
    request, state, result = fixture()
    raw = result[human_question_pause.PAUSE_KEY]
    if fault == "no-capability":
        state.engine_env["workspace_ref"].pop("human_questions_enabled")
    if fault == "numeric-capability":
        state.engine_env["workspace_ref"]["human_questions_enabled"] = 1
    if fault == "no-private":
        result.pop(human_question_pause.PAUSE_KEY)
    if fault == "extra-private":
        raw["token"] = "PRIVATE"
    if fault == "wrong-prompt":
        result["reply"] = "Different question"
    if fault == "wrong-model":
        raw["continuation"]["model"] = "other-model"
    if fault == "bad-transcript":
        raw["continuation"] = None
    if fault == "ambiguous-target":
        state.engine_env["workspace_ref"]["document_context"] = {}
    with pytest.raises(HumanQuestionError):
        human_question_pause.prepare_question(request, state, result, result["reply"])


def test_legacy_result_does_not_require_workspace_or_question_storage():
    assert (
        human_question_pause.prepare_question(None, None, {"metadata": {}}, "ordinary reply")
        is None
    )
    assert persistable_meta({"execution_status": "waiting_user", "awaiting_user": True}, None) == {}


@pytest.mark.parametrize(
    "fault", ["extra", "bad-id", "naive-date", "bad-choice", "accepted-without-job"]
)
def test_public_metadata_does_not_sanitize_private_or_malformed_questions_into_valid_waits(fault):
    request, state, result = fixture()
    public = view(human_question_pause.prepare_question(request, state, result, result["reply"]))
    if fault == "extra":
        public["continuation"] = "PRIVATE"
    if fault == "bad-id":
        public["source_job_id"] = "not-an-id"
    if fault == "naive-date":
        public["expires_at"] = "2026-10-19T10:00:00"
    if fault == "bad-choice":
        public["choices"] = [{"id": "only-one", "label": "x"}]
    if fault == "accepted-without-job":
        public["state"] = "accepted"
    assert (
        persistable_meta({"human_question": public, "execution_status": "waiting_user"}, None) == {}
    )


@pytest.mark.asyncio
async def test_capture_commits_question_accepted_facts_and_recovery_plan_together(monkeypatch):
    request, state, result = fixture()
    events, question_rows = [], {}
    payload = {"thread_id": request.thread_id}
    session = SimpleNamespace(commit=AsyncMock(side_effect=lambda: events.append("commit")))

    async def stage_question(pause, *, session: object):
        events.append("question")
        question_rows["pause"] = pause
        return view(pause)

    question_repo = SimpleNamespace(stage=stage_question)
    monkeypatch.setattr(human_question_pause, "HumanQuestionRepository", lambda _: question_repo)

    async def stage_facts(*args, session):
        events.append("accepted-materialization")
        payload.update(json.loads(args[3]))
        return True

    repository = SimpleNamespace(
        connector=object(),
        stage_accepted_materialization=stage_facts,
        lock_prepared_turn=AsyncMock(
            side_effect=lambda *_args, **_kwargs: {
                "status": ProcessingStatus.PROCESSING,
                "payload": copy.deepcopy(payload),
            }
        ),
    )
    metadata = dict(result["metadata"])
    await early_result_resume.capture_accepted(
        request=request,
        repository=repository,
        session=session,
        state=state,
        execution_result=result,
        reply=result["reply"],
        metadata=metadata,
        prepared=SimpleNamespace(workflow_observations=[], workflow_executions=[]),
        started_at=time.monotonic(),
    )
    assert events == ["question", "accepted-materialization", "commit"]
    assert state.accepted_captured and ACCEPTED_KEY in payload and MATERIALIZATION_KEY in payload
    public = payload[MATERIALIZATION_KEY]["context"]["metadata"]
    assert public["human_question"] == view(question_rows["pause"])
    assert public["execution_status"] == "waiting_user"
    assert "PRIVATE" not in json.dumps(payload) and "PRIVATE" not in json.dumps(metadata)
    assert "PRIVATE-SOURCE" in question_rows["pause"].continuation_json


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_recovery_verifies_question_reference_without_replaying_the_agent(
    monkeypatch, missing
):
    request, state, result = fixture()
    public = view(human_question_pause.prepare_question(request, state, result, result["reply"]))
    current = {**public, "state": "expired"}
    reader = AsyncMock(return_value=None if missing else current)
    monkeypatch.setattr(
        human_question_pause,
        "HumanQuestionRepository",
        lambda _: SimpleNamespace(read_staged=reader),
    )
    args = dict(
        request=request,
        repository=SimpleNamespace(connector=object()),
        session=object(),
        metadata={"human_question": public, "execution_status": "waiting_user"},
    )
    if missing:
        with pytest.raises(JobStateUnavailable):
            await human_question_pause.verify_question_reference(**args)
    else:
        await human_question_pause.verify_question_reference(**args)
        assert args["metadata"]["human_question"]["state"] == "pending"
    assert reader.await_count == 1
    assert parse_public_question(public) == public
