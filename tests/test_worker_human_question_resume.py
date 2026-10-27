"""The worker owns hydration, live capabilities and a fresh accounting attempt."""

import json
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.domain.human_questions.contracts import (
    HumanQuestionError,
    QuestionRefusal,
)
from service.services.chat.domain.human_questions.cost import QuestionCost
from service.services.chat.domain.human_questions.resume import QuestionResume
from service.services.chat.infrastructure.chat_worker import engine_env
from service.services.chat.infrastructure.chat_worker.continuation.resume import (
    RESUME_FRAME_KEY,
    RESUME_JOB_KEY,
    build_question_resume_env,
    hydrate_question_resume,
)
from service.services.chat.infrastructure.chat_worker.execution.run import (
    _prepare_context,
    _reserve_run,
)
from service.services.chat.infrastructure.chat_worker.results import (
    preparation as result_preparation,
)
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)


def request(surface="ide"):
    target = (
        {"repository_id": str(uuid4()), "generation": "a" * 64}
        if surface == "ide"
        else {"path": "documents/slides", "expected_revision": "r1"}
    )
    resumed = QuestionResume(
        uuid4(),
        uuid4(),
        uuid4(),
        surface,
        "saved-model",
        "PRIVATE-TEXT",
        json.dumps(target),
        json.dumps([{"role": "user", "content": "PRIVATE-HISTORY"}]),
    )
    resumed = replace(resumed, cost=QuestionCost.quote(resumed, 1, required=False))
    req = WorkerRunRequest(
        str(resumed.resume_job_id),
        str(uuid4()),
        "UNTRUSTED-BROKER-TEXT",
        str(uuid4()),
        session_data={RESUME_JOB_KEY: str(resumed.resume_job_id), "file_ids": ["foreign"]},
        selected_model="different-model",
        file_context="foreign",
        attachments=["foreign"],
    )
    return req, resumed


def config(enabled=True):
    return SimpleNamespace(human_questions=SimpleNamespace(enabled=enabled))


@pytest.mark.asyncio
async def test_hydration_uses_only_owned_durable_child_and_rejects_broker_context(monkeypatch):
    req, resumed = request()
    load = AsyncMock(return_value=resumed)
    monkeypatch.setattr(
        "service.services.chat.persistence.human_questions.repository.HumanQuestionRepository.load_resume",
        load,
    )
    session = object()
    hydrated = await hydrate_question_resume(req, connector=None, config=config(), session=session)
    assert hydrated.text == "PRIVATE-TEXT" and hydrated.selected_model == "saved-model"
    assert hydrated.question_resume is resumed
    assert hydrated.attachments is None and hydrated.file_context == ""
    assert hydrated.memory_enabled is False and hydrated.multi_intent is False
    assert hydrated.session_data == {
        "session_id": req.thread_id,
        "_ide_context": json.loads(resumed.target_json),
    }
    assert str(load.call_args.args[0]) == req.user_id
    assert str(load.call_args.args[1]) == req.thread_id
    assert str(load.call_args.args[2]) == req.job_id
    assert load.call_args.kwargs["session"] is session
    assert "PRIVATE-HISTORY" not in repr(hydrated)
    load.reset_mock()
    for bad in (config(False), config(1)):
        with pytest.raises(HumanQuestionError):
            await hydrate_question_resume(req, connector=None, config=bad, session=session)
    load.assert_not_awaited()
    load.return_value = QuestionRefusal("human_question_not_found")
    with pytest.raises(HumanQuestionError):
        await hydrate_question_resume(req, connector=None, config=config(), session=session)


@pytest.mark.asyncio
async def test_ordinary_jobs_keep_the_existing_path_without_question_query(monkeypatch):
    req, _ = request()
    req = replace(req, session_data={})
    load = AsyncMock(side_effect=AssertionError("ordinary_job_must_not_load_question"))
    monkeypatch.setattr(
        "service.services.chat.persistence.human_questions.repository.HumanQuestionRepository.load_resume",
        load,
    )
    assert await hydrate_question_resume(req, connector=None, config=config(), session=None) is req
    load.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [None, "pending", "declined"])
async def test_unapproved_private_cost_cannot_reach_the_first_execution_claim(monkeypatch, state):
    from service.services.chat.infrastructure.chat_worker.execution.job_state import (
        JobStateUnavailable,
    )

    req, resumed = request()
    cost = None if state is None else QuestionCost.quote(resumed, 100, required=True)
    if state == "declined":
        cost = cost.model_copy(update={"state": state, "decided_at": time.time()})
    resumed = replace(resumed, cost=cost)
    monkeypatch.setattr(
        "service.services.chat.persistence.human_questions.repository.HumanQuestionRepository.load_resume",
        AsyncMock(return_value=resumed),
    )
    with pytest.raises(JobStateUnavailable):
        await hydrate_question_resume(req, connector=None, config=config(), session=object())


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["hydration_storage", "hydration_refused", "billing"])
async def test_owned_run_does_not_turn_unknown_resume_or_cost_into_a_new_user_request(
    monkeypatch, fault, caplog
):
    from contextlib import asynccontextmanager
    from functools import partial
    from unittest.mock import Mock

    from service.services.chat.infrastructure.chat_worker.billing.reservation.preflight import (
        reserve_credits_or_short_circuit,
    )
    from service.services.chat.infrastructure.chat_worker.context import targets as project_targets
    from service.services.chat.infrastructure.chat_worker.execution import run as run_execution
    from service.services.chat.infrastructure.chat_worker.run_contracts import WorkerExecutionHooks

    req, resumed = request()
    session = AsyncMock()

    @asynccontextmanager
    async def transaction():
        yield session

    load = AsyncMock(return_value=resumed)
    if fault == "hydration_storage":
        load.side_effect = RuntimeError("PRIVATE_STORAGE")
    elif fault == "hydration_refused":
        load.return_value = QuestionRefusal("human_question_binding_changed")
    monkeypatch.setattr(
        "service.services.chat.persistence.human_questions.repository.HumanQuestionRepository.load_resume",
        load,
    )
    repository = SimpleNamespace(claim_chat_execution=AsyncMock(return_value=True))
    monkeypatch.setattr(
        "service.services.jobs.persistence.job_repository.JobRepository", lambda *_args: repository
    )
    monkeypatch.setattr(project_targets, "validate_run_targets", AsyncMock(return_value=None))
    billing = SimpleNamespace(
        has_sufficient_credits=AsyncMock(side_effect=RuntimeError("PRIVATE_COST"))
    )
    monkeypatch.setattr(
        "service.services.billing.application.billing_service.BillingService",
        lambda *_args: billing,
    )
    publisher = Mock()
    hooks = {field: AsyncMock() for field in WorkerExecutionHooks.__dataclass_fields__}
    hooks.update(
        prepared_results=None,
        bind_runtime_settings=Mock(),
        publisher_factory=Mock(return_value=publisher),
        build_file_service=Mock(return_value=None),
        redelivery_short_circuit=AsyncMock(return_value=None),
        reservation_context_chars=lambda **kw: 0,
        reserve_credits=partial(
            reserve_credits_or_short_circuit,
            overlay_billing=lambda *_args: object(),
            estimate_credits=AsyncMock(),
            emit_expensive=AsyncMock(),
            emit_insufficient=AsyncMock(),
        ),
    )
    result = await run_execution._execute_owned_job(
        req,
        hooks=WorkerExecutionHooks(**hooks),
        dependency_factory=SimpleNamespace(create_redis_client=lambda _config: None),
        agent_execution=object(),
        config=config(),
        pg_connector=SimpleNamespace(get_session_context=transaction),
    )
    assert result["status"] == "error"
    session.rollback.assert_awaited_once()
    if fault == "hydration_storage":
        # A failed read is not proof that the accepted question/child is invalid.
        hooks["handle_failure"].assert_not_awaited()
        repository.claim_chat_execution.assert_not_awaited()
    else:
        hooks["handle_failure"].assert_awaited_once()
        assert hooks["handle_failure"].call_args.kwargs["user_text"] == ""
    for name in ("run_with_cancel", "charge_and_describe", "persist_chat_turn"):
        hooks[name].assert_not_awaited()
    publisher.close.assert_called_once()
    assert "PRIVATE_STORAGE" not in str(result) + caplog.text
    assert "PRIVATE_COST" not in str(result) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", [None, "expired", "owner", "rebound", "unavailable", "capability"]
)
async def test_pdf_resume_passively_rechecks_binding_and_never_allocates(monkeypatch, fault):
    from service.infrastructure import workspace_client
    from service.services.chat.application.documents import context as document_context_service

    req, resumed = request("pdf")
    req = replace(
        req,
        question_resume=resumed,
        session_data={"_document_context": json.loads(resumed.target_json)},
    )
    binding = {"workspace_id": "owned", "user_id": req.user_id, "expires_at": time.time() + 100}
    if fault == "expired":
        binding["expires_at"] = time.time() - 1
    if fault == "owner":
        binding["user_id"] = str(uuid4())
    state = "unavailable" if fault == "unavailable" else "ready"
    read = AsyncMock(
        side_effect=[
            (state, binding),
            (state, {**binding, "workspace_id": "other"} if fault == "rebound" else binding),
        ]
    )
    monkeypatch.setattr(workspace_client, "read_binding_state", read)
    validate = AsyncMock(
        return_value={**req.session_data["_document_context"], "tools_auto_approved": True}
    )
    monkeypatch.setattr(document_context_service, "validate_document_context", validate)
    allocate = AsyncMock(side_effect=AssertionError("resume_must_never_allocate"))
    monkeypatch.setattr(workspace_client, "ensure_workspace", allocate)
    env = AsyncMock(
        return_value={
            "workspace_ref": {"coordination_capability": "PRIVATE"} if fault != "capability" else {}
        }
    )
    monkeypatch.setattr(engine_env, "build_engine_env", env)
    if fault is not None:
        with pytest.raises(HumanQuestionError):
            await build_question_resume_env(req, redis=None, connector=None)
    else:
        result = await build_question_resume_env(req, redis=None, connector=None)
        assert env.call_args.kwargs["existing_document_binding"] == binding
        ref = result["workspace_ref"]
        assert ref["human_questions_enabled"] is True
        assert ref[RESUME_FRAME_KEY]["model"] == resumed.model
        assert ref[RESUME_FRAME_KEY]["messages"] == json.loads(resumed.messages_json)
    allocate.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_preparation_skips_memory_history_file_recall_and_attachment_import(
    monkeypatch,
):
    req, resumed = request()
    req = replace(req, question_resume=resumed)
    env = {"workspace_ref": {"coordination_capability": "PRIVATE"}}
    build = AsyncMock(return_value=env)
    monkeypatch.setattr(
        "service.services.chat.infrastructure.chat_worker.continuation.resume.build_question_resume_env",
        build,
    )
    state = MutableRunState()
    prepared = await _prepare_context(
        req,
        config=config(),
        pg_connector=None,
        redis_client=None,
        session=None,
        pseudo_session=None,
        publisher=SimpleNamespace(publish_payload=lambda payload: None),
        state=state,
        hooks=SimpleNamespace(),
        file_service=None,
    )
    assert prepared.history_messages == [] and prepared.memory_parts == ("", "")
    assert prepared.attachments == [] and prepared.file_context == ""
    assert state.engine_env is env


@pytest.mark.asyncio
async def test_resume_reserves_for_frozen_context_without_restoring_a_second_history(monkeypatch):
    from service.models.key_value import ProcessingStatus
    from service.services.chat.infrastructure.chat_worker.context import targets as project_targets

    req, resumed = request()
    req = replace(req, question_resume=resumed, attachments=None, session_data={})
    monkeypatch.setattr(project_targets, "validate_run_targets", AsyncMock(return_value=None))
    hooks = SimpleNamespace(
        update_job_status=AsyncMock(),
        restore_history=AsyncMock(),
        reservation_context_chars=lambda **kwargs: 0,
        reserve_credits=AsyncMock(return_value=(None, "reservation", 1)),
    )
    await _reserve_run(
        req,
        config=config(),
        pg_connector=None,
        publisher=None,
        job_repo=None,
        session=None,
        state=MutableRunState(),
        hooks=hooks,
        redis_client=None,
        file_service=None,
    )
    hooks.restore_history.assert_not_awaited()
    assert hooks.update_job_status.call_args.args[2] == ProcessingStatus.PROCESSING
    assert hooks.reserve_credits.call_args.kwargs["context_chars"] >= len(resumed.messages_json)
    assert hooks.reserve_credits.call_args.kwargs["confirmation_context"]["skip_user_turn"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("funded", [True, False])
async def test_resume_keeps_billing_guard_and_never_duplicates_user_turn(monkeypatch, funded):
    from service.services.chat.infrastructure.chat_worker.billing.reservation.preflight import (
        reserve_credits_or_short_circuit,
    )

    billing = SimpleNamespace(
        has_sufficient_credits=AsyncMock(return_value=funded), reserve=AsyncMock()
    )
    monkeypatch.setattr(
        "service.services.billing.application.billing_service.BillingService", lambda *args: billing
    )
    cfg = SimpleNamespace(
        expensive_run_confirmation_credits=10, insufficient_credits_message="Нет кредитов"
    )
    expensive, insufficient = AsyncMock(), AsyncMock(return_value={"unfunded": True})
    operation = reserve_credits_or_short_circuit(
        pg_connector=None,
        config=None,
        publisher=None,
        job_repo=None,
        session=None,
        job_id="child",
        thread_id="thread",
        text="ORIGINAL",
        user_id="owner",
        selected_model="saved-model",
        context_chars=100,
        attachments=None,
        expensive_run_confirmed=False,
        confirmation_context={"skip_user_turn": True},
        overlay_billing=lambda *args: cfg,
        estimate_credits=AsyncMock(return_value=100),
        emit_expensive=expensive,
        emit_insufficient=insufficient,
    )
    if funded:
        with pytest.raises(HumanQuestionError):
            await operation
        insufficient.assert_not_awaited()
    else:
        assert (await operation)[0] == {"unfunded": True}
        assert insufficient.call_args.kwargs["text"] == ""
    expensive.assert_not_awaited()
    billing.reserve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("resuming", [True, False])
@pytest.mark.parametrize("failure_at", ["funds", "estimate", "reserve"])
async def test_resume_billing_outage_is_fail_closed_without_changing_ordinary_chat(
    monkeypatch, resuming, failure_at
):
    from service.services.chat.infrastructure.chat_worker.billing.reservation.preflight import (
        reserve_credits_or_short_circuit,
    )

    billing = SimpleNamespace(
        has_sufficient_credits=AsyncMock(return_value=True),
        reserve=AsyncMock(return_value="hold"),
    )
    estimate = AsyncMock(return_value=5)
    failures = {
        "funds": billing.has_sufficient_credits,
        "estimate": estimate,
        "reserve": billing.reserve,
    }
    failures[failure_at].side_effect = RuntimeError("PRIVATE_BILLING_FAILURE")
    monkeypatch.setattr(
        "service.services.billing.application.billing_service.BillingService", lambda *args: billing
    )
    expensive, insufficient = AsyncMock(), AsyncMock()
    operation = reserve_credits_or_short_circuit(
        pg_connector=None,
        config=None,
        publisher=None,
        job_repo=None,
        session=None,
        job_id="child",
        thread_id="thread",
        text="ORIGINAL",
        user_id="owner",
        selected_model="saved-model",
        context_chars=100,
        attachments=None,
        expensive_run_confirmed=True,
        confirmation_context={"skip_user_turn": True} if resuming else {},
        overlay_billing=lambda *args: SimpleNamespace(expensive_run_confirmation_credits=10),
        estimate_credits=estimate,
        emit_expensive=expensive,
        emit_insufficient=insufficient,
    )
    if resuming:
        with pytest.raises(HumanQuestionError, match="^human_question_unavailable$"):
            await operation
    else:
        assert await operation == (None, None, 0)
    expensive.assert_not_awaited()
    insufficient.assert_not_awaited()
    if failure_at != "reserve":
        billing.reserve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "estimate,threshold,allowed", [(100, 10, True), (101, 10, False), (101, 1000, False)]
)
async def test_same_child_cost_grant_allows_only_the_accepted_estimate(
    monkeypatch, estimate, threshold, allowed
):
    from service.services.chat.infrastructure.chat_worker.billing.reservation.preflight import (
        reserve_credits_or_short_circuit,
    )

    _, resume = request()
    cost = QuestionCost.quote(resume, 100, required=True).model_copy(
        update={"state": "accepted", "decided_at": time.time()}
    )
    billing = SimpleNamespace(
        has_sufficient_credits=AsyncMock(return_value=True),
        reserve=AsyncMock(return_value="same-hold"),
    )
    monkeypatch.setattr(
        "service.services.billing.application.billing_service.BillingService",
        lambda *_args: billing,
    )
    operation = reserve_credits_or_short_circuit(
        pg_connector=None,
        config=None,
        publisher=None,
        job_repo=None,
        session=None,
        job_id=str(resume.resume_job_id),
        thread_id="thread",
        text=resume.text,
        user_id="owner",
        selected_model=resume.model,
        context_chars=100,
        attachments=None,
        expensive_run_confirmed=False,
        confirmation_context={"skip_user_turn": True, "question_cost": cost},
        overlay_billing=lambda *_args: SimpleNamespace(
            expensive_run_confirmation_credits=threshold
        ),
        estimate_credits=AsyncMock(return_value=estimate),
        emit_expensive=AsyncMock(),
        emit_insufficient=AsyncMock(),
    )
    if allowed:
        assert await operation == (None, "same-hold", 100)
        billing.reserve.assert_awaited_once()
    else:
        with pytest.raises(HumanQuestionError):
            await operation
        billing.reserve.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_terminal_publication_does_not_persist_original_user_text_again(monkeypatch):
    from unittest.mock import Mock

    from service.services.chat.infrastructure.chat_worker.execution import run as run_execution
    from service.services.chat.infrastructure.chat_worker.phases import RunPhase

    req, resumed = request()
    req = replace(req, question_resume=resumed, memory_enabled=False)
    state = MutableRunState()
    state.phase.advance(RunPhase.RESERVED)
    state.phase.advance(RunPhase.EXECUTING)
    hooks = SimpleNamespace(
        prepared_results=None,
        reply_or_provider_failure=Mock(return_value=("Продолжение завершено", {})),
        record_catalog_events=AsyncMock(),
        charge_and_describe=AsyncMock(return_value=(0, {})),
        persist_chat_turn=AsyncMock(),
        update_job_status=AsyncMock(),
        publish_committed_turn=AsyncMock(),
        extract_memory=AsyncMock(),
    )
    monkeypatch.setattr(
        result_preparation, "persist_all_artifacts", AsyncMock(return_value=(None, {}))
    )
    result = await run_execution._finalize_success(
        req,
        {"resolved_model": resumed.model, "reply_parts_count": 1, "reply_chars_count": 20},
        SimpleNamespace(workflow_observations=[], workflow_executions=[]),
        config=None,
        pg_connector=None,
        redis_client=None,
        publisher=Mock(),
        job_repo=None,
        file_service=None,
        session=AsyncMock(),
        state=state,
        hooks=hooks,
        started_at=0,
    )
    assert result["status"] == "success"
    assert hooks.persist_chat_turn.call_args.kwargs["user_text"] == ""
    assert hooks.persist_chat_turn.call_args.kwargs["user_metadata"] == {}
    assert hooks.publish_committed_turn.call_args.kwargs["memory_enabled"] is False


@pytest.mark.asyncio
async def test_explicit_pdf_resume_binding_bypasses_automatic_allocation(monkeypatch):
    from service.infrastructure import workspace_client
    from service.services.chat.infrastructure.chat_worker.billing import (
        video_grant as video_stt_grant,
    )

    allocate = AsyncMock(side_effect=AssertionError("must_not_allocate"))
    monkeypatch.setattr(workspace_client, "ensure_workspace", allocate)
    monkeypatch.setattr(workspace_client, "import_files", AsyncMock())
    monkeypatch.setattr(video_stt_grant, "attach_video_stt_grant", AsyncMock())
    binding = {
        "workspace_id": "owned",
        "user_id": "owner",
        "token": "PRIVATE",
        "expires_at": time.time() + 100,
    }
    target = {"path": "documents/slides", "project_id": "owned-project"}
    result = await engine_env.build_engine_env(
        None,
        "thread",
        "owner",
        [],
        session_data={"_document_context": target},
        existing_document_binding=binding,
    )
    assert result["workspace_ref"]["workspace_id"] == "owned"
    assert result["workspace_ref"]["document_context"] == target
    assert binding.get("document_context") is None  # No mutation of stored binding.
    allocate.assert_not_awaited()
