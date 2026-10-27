"""Prepared results resume settlement, not provider execution or artifact collection."""

import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.execution import job_state
from service.services.chat.infrastructure.chat_worker.execution import run as run_execution
from service.services.chat.infrastructure.chat_worker.phases import RunPhase
from service.services.chat.infrastructure.chat_worker.results import (
    preparation as result_preparation,
)
from service.services.chat.infrastructure.chat_worker.results.accepted import ACCEPTED_KEY
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    CHECKPOINT_KEY,
    PreparedCheckpointInvalid,
    PreparedTurnCheckpoint,
)
from service.services.chat.infrastructure.chat_worker.results.prepared import (
    PreparedResultCoordinator,
)
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerExecutionHooks,
    WorkerRunRequest,
)


def prepared_fixture():
    request = WorkerRunRequest(str(uuid4()), str(uuid4()), "synthetic", str(uuid4()))
    private = {
        "reservation_id": str(uuid4()),
        "reserved_estimate": 70,
        "workspace_id": None,
        "expires_at": None,
        "publications": [],
        "pricing": {"is_complex": True, "tools": ["web_search", "web_search"]},
        "elapsed_seconds": 4.5,
        "primary_file_id": None,
    }
    usage = {
        "prompt_tokens": 30,
        "completion_tokens": 3,
        "total_tokens": 33,
        "per_call_usage": [
            {
                "provider": "openai",
                "model": "synthetic",
                "call_id": "receipt-1",
                "prompt": 30,
                "completion": 3,
            }
        ],
    }
    public = {"selected_model": "synthetic"}
    envelope = PreparedTurnCheckpoint.create(
        job_id=request.job_id,
        owner_id=request.user_id,
        thread_id=request.thread_id,
        reply="accepted synthetic reply",
        model="synthetic",
        metadata={"public": public, "private": private},
        usage=usage,
    ).payload()
    return request, private, usage, public, envelope


def repository(envelope, *, status=ProcessingStatus.PROCESSING):
    return SimpleNamespace(
        lock_prepared_turn=AsyncMock(
            return_value={
                "status": status,
                "payload": {CHECKPOINT_KEY: envelope},
            }
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [{"corrupt": True}, None, "valid"])
async def test_early_latch_without_prepared_result_cannot_be_reexecuted(accepted):
    from service.services.chat.infrastructure.chat_worker.results.accepted import accepted_turn

    request, _, usage, _, _ = prepared_fixture()
    if accepted == "valid":
        accepted = accepted_turn(
            job_id=request.job_id,
            owner_id=request.user_id,
            thread_id=request.thread_id,
            reply="accepted",
            model="synthetic",
            usage=usage,
        ).payload()
    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(
            return_value={
                "status": ProcessingStatus.PROCESSING,
                "payload": {ACCEPTED_KEY: accepted},
            }
        )
    )
    with pytest.raises(job_state.JobStateUnavailable):
        await PreparedResultCoordinator().restore(
            request=request,
            repository=repo,
            session=AsyncMock(),
            state=MutableRunState(),
            file_service=object(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["artifacts", "catalog"])
async def test_pre_checkpoint_fault_reproduces_accepted_result_persistence_gap(
    monkeypatch, fault, caplog
):
    """Negative evidence: this is a known gap, not a recovery acceptance test."""
    request, _, usage, _, _ = prepared_fixture()
    coordinator = SimpleNamespace(capture=AsyncMock())
    catalog = AsyncMock()
    artifacts = AsyncMock(return_value=(None, {}))
    target = artifacts if fault == "artifacts" else catalog
    target.side_effect = RuntimeError("synthetic-pre-checkpoint-fault")
    monkeypatch.setattr(result_preparation, "persist_all_artifacts", artifacts)
    state = MutableRunState()
    state.phase.advance(RunPhase.RESERVED)
    state.phase.advance(RunPhase.EXECUTING)
    hooks = SimpleNamespace(
        reply_or_provider_failure=Mock(return_value=("accepted synthetic reply", {})),
        record_catalog_events=catalog,
        prepared_results=coordinator,
        charge_and_describe=AsyncMock(),
    )
    with pytest.raises(RuntimeError, match="synthetic-pre-checkpoint-fault"):
        await run_execution._finalize_success(
            request,
            {
                **usage,
                "resolved_model": "synthetic",
                "reply_parts_count": 1,
                "reply_chars_count": 24,
            },
            SimpleNamespace(workflow_observations=[], workflow_executions=[]),
            config=None,
            pg_connector=None,
            redis_client=None,
            publisher=Mock(),
            job_repo=object(),
            file_service=object(),
            session=AsyncMock(),
            state=state,
            hooks=hooks,
            started_at=time.monotonic(),
        )
    assert state.phase.phase is RunPhase.RESULT_LATCHED
    coordinator.capture.assert_not_awaited()
    hooks.charge_and_describe.assert_not_awaited()
    assert "synthetic-pre-checkpoint-fault" not in caplog.text


@pytest.mark.asyncio
async def test_capture_commits_owned_projection_before_reacquiring_settlement_lock():
    request, _, usage, _, _ = prepared_fixture()
    saved = {}
    order = []
    repo = SimpleNamespace()

    async def stage(*args, **kwargs):
        saved.update(json.loads(args[3]))
        order.append("stage")
        return True

    async def lock(*args, **kwargs):
        order.append("lock")
        payload = {"thread_id": request.thread_id}
        if saved:
            payload[CHECKPOINT_KEY] = saved
        return {"status": ProcessingStatus.PROCESSING, "payload": payload}

    repo.stage_prepared_turn = stage
    repo.lock_prepared_turn = lock
    session = AsyncMock()
    session.commit.side_effect = lambda: order.append("commit")
    file_id = str(uuid4())
    metadata = {
        "generated_files": [
            {
                "file_id": file_id,
                "filename": "sample.pdf",
                "file_key": "private-storage-marker",
                "file_url": "private-url-marker",
            }
        ]
    }
    execution = {**usage, "metadata": {}, "resolved_model": "synthetic"}
    execution["per_call_usage"] = [
        {**usage["per_call_usage"][0], "arguments": "private-arguments-marker"}
    ]
    await PreparedResultCoordinator().capture(
        request=request,
        session=session,
        repository=repo,
        state=MutableRunState(),
        execution_result=execution,
        reply="accepted",
        metadata=metadata,
        file_url="private-url-marker",
        started_at=time.monotonic(),
    )
    assert order == ["lock", "stage", "commit", "lock"]
    encoded = json.dumps(saved)
    assert "private-storage-marker" not in encoded
    assert "private-url-marker" not in encoded
    assert "private-arguments-marker" not in encoded
    assert saved["body"]["metadata"]["private"]["primary_file_id"] == file_id


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["stage", "commit", "lock"])
async def test_capture_storage_outage_is_bounded_and_preserves_possible_accepted_result(
    fault, caplog
):
    request, _, usage, _, _ = prepared_fixture()
    session = AsyncMock()
    repo = SimpleNamespace(
        stage_prepared_turn=AsyncMock(return_value=True), lock_prepared_turn=AsyncMock()
    )
    target = {
        "stage": repo.stage_prepared_turn,
        "commit": session.commit,
        "lock": repo.lock_prepared_turn,
    }[fault]
    target.side_effect = RuntimeError("private-checkpoint-storage-marker")
    with pytest.raises(job_state.JobStateUnavailable) as caught:
        await PreparedResultCoordinator().capture(
            request=request,
            session=session,
            repository=repo,
            state=MutableRunState(),
            execution_result={**usage, "metadata": {}, "resolved_model": "synthetic"},
            reply="accepted",
            metadata={},
            file_url=None,
            started_at=time.monotonic(),
        )
    assert "private-checkpoint-storage-marker" not in str(caught.value) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [ProcessingStatus.SUCCESS, ProcessingStatus.FAILURE])
async def test_terminal_race_is_not_reinterpreted_as_fresh_work(status):
    request, _, _, _, envelope = prepared_fixture()
    with pytest.raises(job_state.JobStateUnavailable):
        await PreparedResultCoordinator().restore(
            request=request,
            repository=repository(envelope, status=status),
            session=AsyncMock(),
            state=MutableRunState(),
            file_service=object(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("deferred", [False, True])
async def test_delivery_projection_preserves_canonical_model_reply_and_receipts(deferred):
    from service.infrastructure.agents_client.required_artifacts import (
        DELIVERY_DEFERRED_REPLY,
        DELIVERY_READY_REPLY,
    )

    request, _, usage, _, _ = prepared_fixture()
    public = {"execution_status": "deferred" if deferred else "completed"}
    file_id = str(uuid4())
    if not deferred:
        public["generated_files"] = [{"file_id": file_id, "filename": "notes.md"}]
    displayed = DELIVERY_DEFERRED_REPLY if deferred else DELIVERY_READY_REPLY
    stored = None

    async def stage(*args, **kwargs):
        nonlocal stored
        stored = json.loads(args[3])
        return True

    async def lock(*args, **kwargs):
        payload = {"thread_id": request.thread_id}
        if stored is not None:
            payload[CHECKPOINT_KEY] = stored
        return {"status": ProcessingStatus.PROCESSING, "payload": payload}

    repo = SimpleNamespace(stage_prepared_turn=stage, lock_prepared_turn=lock)
    await PreparedResultCoordinator().capture(
        request=request,
        session=AsyncMock(),
        repository=repo,
        state=MutableRunState(),
        execution_result={**usage, "resolved_model": "synthetic"},
        reply=displayed,
        canonical_reply="immutable model reply",
        metadata=public,
        file_url=None,
        started_at=time.monotonic(),
    )
    assert stored["body"]["reply"] == "immutable model reply"
    assert stored["body"]["usage"] == usage
    state, session = MutableRunState(), AsyncMock()
    session.scalar.return_value = 0
    files = SimpleNamespace(
        fetch_file_metadata=AsyncMock(return_value=SimpleNamespace(file_key="private")),
        get_presigned_url_by_key=AsyncMock(return_value="private-capability"),
    )
    assert await PreparedResultCoordinator().restore(
        request=request, repository=repo, session=session, state=state, file_service=files
    )
    assert state.restored_result["reply"] == displayed
    assert state.restored_result["usage"] == usage


@pytest.mark.parametrize(
    ("displayed", "public"),
    [
        ("PRIVATE_RAW_REWRITE", {}),
        ("ready", {}),
    ],
)
def test_projection_does_not_authorize_arbitrary_model_reply_rewrite(displayed, public):
    from service.services.chat.infrastructure.chat_worker.results.prepared import _reply_projection

    with pytest.raises(PreparedCheckpointInvalid) as caught:
        _reply_projection("canonical", displayed, public)
    assert str(caught.value) == "Prepared result unavailable"


@pytest.mark.asyncio
async def test_generated_files_are_rebound_through_owner_checked_library_metadata():
    request, private, usage, public, _ = prepared_fixture()
    file_id = str(uuid4())
    public["generated_files"] = [{"file_id": file_id, "filename": "sample.pdf"}]
    private["primary_file_id"] = file_id
    envelope = PreparedTurnCheckpoint.create(
        job_id=request.job_id,
        owner_id=request.user_id,
        thread_id=request.thread_id,
        reply="accepted",
        model="synthetic",
        metadata={"public": public, "private": private},
        usage=usage,
    ).payload()
    files = SimpleNamespace(
        fetch_file_metadata=AsyncMock(return_value=SimpleNamespace(file_key="private-storage")),
        get_presigned_url_by_key=AsyncMock(return_value="renewed-private-url"),
    )
    session = AsyncMock()
    session.scalar.return_value = 10
    state = MutableRunState()
    assert await PreparedResultCoordinator().restore(
        request=request,
        repository=repository(envelope),
        session=session,
        state=state,
        file_service=files,
    )
    assert files.fetch_file_metadata.await_args.args[0] == request.user_id
    assert str(files.fetch_file_metadata.await_args.args[1]) == file_id
    assert state.restored_result["file_url"] == "renewed-private-url"
    assert state.reservation_id == private["reservation_id"]
    assert state.settled_credits == 10
    assert "accepted" not in repr(state)


async def execute_resume(
    monkeypatch,
    request,
    repo,
    *,
    fail_persistence=False,
    fresh_result=None,
    settled_credits=10,
    charge_credits=2,
):
    session = AsyncMock()
    session.scalar.return_value = settled_credits
    lease_session = AsyncMock()
    lease_session.scalar.return_value = True
    session_count = 0
    order = []

    @asynccontextmanager
    async def transaction():
        nonlocal session_count
        session_count += 1
        yield lease_session if session_count == 1 else session

    async def charge(**kwargs):
        order.append("charge")
        assert kwargs["pricing_inputs"] == (True, ["web_search", "web_search"])
        assert kwargs["execution_result"]["per_call_usage"][0]["call_id"] == "receipt-1"
        assert kwargs["reserved_estimate"] == 70
        return charge_credits, {**kwargs["metadata"], "usage": {"credits": charge_credits}}

    publisher = Mock()
    values = {field: AsyncMock() for field in WorkerExecutionHooks.__dataclass_fields__}
    values.update(
        prepared_results=PreparedResultCoordinator(),
        bind_runtime_settings=Mock(),
        publisher_factory=Mock(return_value=publisher),
        build_file_service=Mock(),
        redelivery_short_circuit=AsyncMock(return_value=None),
        charge_and_describe=charge,
        persist_chat_turn=AsyncMock(side_effect=lambda **kw: order.append("persist")),
        update_job_status=AsyncMock(side_effect=lambda *args: order.append("terminal")),
        publish_committed_turn=AsyncMock(side_effect=lambda **kw: order.append("publish")),
    )
    if fail_persistence:
        values["persist_chat_turn"].side_effect = RuntimeError("private-persistence-marker")
    if fresh_result is not None:
        values["reply_or_provider_failure"] = Mock(return_value=(fresh_result["reply"], {}))

        async def fresh(*args, state, **kwargs):
            state.phase.advance(RunPhase.RESERVED)
            state.phase.advance(RunPhase.EXECUTING)
            return (
                fresh_result,
                SimpleNamespace(workflow_observations=[], workflow_executions=[]),
                None,
            )

        monkeypatch.setattr(run_execution, "_run_or_restore", fresh)
    session.commit.side_effect = lambda: order.append("commit")
    monkeypatch.setattr(
        "service.services.jobs.persistence.job_repository.JobRepository", lambda _: repo
    )
    forbidden = {
        name: AsyncMock(side_effect=AssertionError("fresh execution on resume"))
        for name in ("_reserve_run", "_prepare_context", "_execute_agent", "persist_all_artifacts")
    }
    for name, callback in forbidden.items():
        owner = result_preparation if name == "persist_all_artifacts" else run_execution
        monkeypatch.setattr(owner, name, callback)
    result = await run_execution.execute_chat_job(
        request,
        hooks=WorkerExecutionHooks(**values),
        dependency_factory=SimpleNamespace(
            create_pg_connector=lambda _: SimpleNamespace(get_session_context=transaction),
            create_redis_client=lambda _: None,
        ),
        agent_execution=object(),
    )
    for name, callback in forbidden.items():
        if fresh_result is not None and name == "persist_all_artifacts":
            callback.assert_awaited_once()
        else:
            callback.assert_not_awaited()
    values["reserve_credits"].assert_not_awaited()
    values["record_catalog_events"].assert_not_awaited()
    publisher.close.assert_called_once()
    return result, values, session, order


@pytest.mark.asyncio
async def test_worker_restores_prepared_receipts_and_finishes_without_another_provider(monkeypatch):
    request, _, _, _, envelope = prepared_fixture()
    result, hooks, session, order = await execute_resume(monkeypatch, request, repository(envelope))
    assert result["status"] == "success"
    assert result["reply"] == "accepted synthetic reply"
    assert result["metadata"]["usage"]["credits"] == 12
    assert order == ["charge", "persist", "terminal", "commit", "publish"]
    hooks["handle_failure"].assert_not_awaited()
    assert (
        "_document_publications"
        not in hooks["persist_chat_turn"].await_args.kwargs["assistant_metadata"]
    )
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_promotes_early_plan_and_finishes_without_provider_or_artifact_io(monkeypatch):
    from service.services.chat.infrastructure.chat_worker.materialization.recovery import (
        MATERIALIZATION_KEY,
    )
    from service.services.chat.infrastructure.chat_worker.results.accepted import accepted_turn

    request, private, usage, public, _ = prepared_fixture()
    accepted = accepted_turn(
        job_id=request.job_id,
        owner_id=request.user_id,
        thread_id=request.thread_id,
        reply="accepted synthetic reply",
        model="synthetic",
        usage=usage,
    )
    plan = {key: private[key] for key in private if key != "primary_file_id"}
    plan.update(
        {
            "version": 2,
            "library_files": [],
            "unresolved_assets": 0,
            "context": {"metadata": public, "observations": [], "executions": []},
        }
    )
    payload = {
        "thread_id": request.thread_id,
        ACCEPTED_KEY: accepted.payload(),
        MATERIALIZATION_KEY: plan,
    }

    async def stage(*args, **kwargs):
        payload[CHECKPOINT_KEY] = json.loads(args[3])
        return True

    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(
            return_value={"status": ProcessingStatus.PROCESSING, "payload": payload}
        ),
        stage_prepared_turn=stage,
    )
    result, hooks, session, order = await execute_resume(monkeypatch, request, repo)
    assert result["status"] == "success"
    assert result["reply"] == accepted.payload()["body"]["reply"]
    assert payload[CHECKPOINT_KEY]["body"]["usage"] == usage
    assert order == ["commit", "charge", "persist", "terminal", "commit", "publish"]
    hooks["handle_failure"].assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_question", [False, True])
async def test_question_pause_recovers_the_owned_reference_without_provider_or_file_replay(
    monkeypatch, missing_question
):
    from datetime import UTC, datetime
    from uuid import UUID, uuid5

    from service.services.chat.infrastructure.chat_worker.continuation import (
        pause as human_question_pause,
    )
    from service.services.chat.infrastructure.chat_worker.materialization.recovery import (
        MATERIALIZATION_KEY,
    )
    from service.services.chat.infrastructure.chat_worker.results.accepted import accepted_turn

    request, private, usage, _, _ = prepared_fixture()
    question = {
        "question_id": str(uuid5(UUID(request.job_id), "gpthub:human-question:v1")),
        "source_job_id": request.job_id,
        "surface": "ide",
        "project_id": str(uuid4()),
        "prompt": "Which structure should we add?",
        "choices": [],
        "state": "pending",
        "expires_at": datetime.now(UTC).isoformat(),
        "resume_job_id": None,
    }
    accepted = accepted_turn(
        job_id=request.job_id,
        owner_id=request.user_id,
        thread_id=request.thread_id,
        reply=question["prompt"],
        model="synthetic",
        usage=usage,
    )
    plan = {key: private[key] for key in private if key != "primary_file_id"}
    plan.update(
        version=2,
        library_files=[],
        unresolved_assets=0,
        context={
            "metadata": {"execution_status": "waiting_user", "human_question": question},
            "observations": [],
            "executions": [],
        },
    )
    payload = {
        "thread_id": request.thread_id,
        ACCEPTED_KEY: accepted.payload(),
        MATERIALIZATION_KEY: plan,
    }

    async def stage(*args, **kwargs):
        payload[CHECKPOINT_KEY] = json.loads(args[3])
        return True

    repo = SimpleNamespace(
        connector=object(),
        stage_prepared_turn=stage,
        lock_prepared_turn=AsyncMock(
            return_value={"status": ProcessingStatus.PROCESSING, "payload": payload}
        ),
    )
    reader = AsyncMock(return_value=None if missing_question else {**question, "state": "expired"})
    monkeypatch.setattr(
        human_question_pause,
        "HumanQuestionRepository",
        lambda _: SimpleNamespace(read_staged=reader),
    )
    result, hooks, _, order = await execute_resume(monkeypatch, request, repo)
    if missing_question:
        assert result["status"] == "error" and order == []
        hooks["persist_chat_turn"].assert_not_awaited()
        hooks["update_job_status"].assert_not_awaited()
        assert CHECKPOINT_KEY not in payload
    else:
        assert result["status"] == "success"
        assert result["metadata"]["execution_status"] == "waiting_user"
        assert result["metadata"]["human_question"] == question
        assert order == ["commit", "charge", "persist", "terminal", "commit", "publish"]
        assert (
            hooks["persist_chat_turn"].await_args.kwargs["assistant_metadata"]["human_question"]
            == question
        )
    hooks["handle_failure"].assert_not_awaited()


@pytest.mark.asyncio
async def test_fresh_worker_artifact_failure_preserves_atomic_early_latch(monkeypatch):
    from service.services.chat.infrastructure.chat_worker.materialization.recovery import (
        MATERIALIZATION_KEY,
    )

    request, _, usage, _, _ = prepared_fixture()
    payload = {"thread_id": request.thread_id}

    async def stage(*args, **kwargs):
        payload.update(json.loads(args[3]))
        return True

    repo = SimpleNamespace(
        stage_accepted_materialization=stage,
        lock_prepared_turn=AsyncMock(
            return_value={"status": ProcessingStatus.PROCESSING, "payload": payload}
        ),
    )
    result, hooks, session, order = await execute_resume(
        monkeypatch,
        request,
        repo,
        fresh_result={
            **usage,
            "reply": "accepted model reply",
            "resolved_model": "synthetic",
            "reply_parts_count": 1,
            "reply_chars_count": 20,
        },
    )
    assert result["status"] == "error" and result["status_code"] == 503
    assert order == ["commit"]
    assert payload[ACCEPTED_KEY]["body"]["usage"] == usage
    assert payload[MATERIALIZATION_KEY]["context"]["metadata"] == {}
    assert CHECKPOINT_KEY not in payload
    hooks["handle_failure"].assert_not_awaited()
    hooks["persist_chat_turn"].assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_preserves_early_latch_without_new_provider_or_failure_settlement(monkeypatch):
    request, *_ = prepared_fixture()
    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(
            return_value={
                "status": ProcessingStatus.PROCESSING,
                "payload": {ACCEPTED_KEY: {"private-marker": "accepted"}},
            }
        )
    )
    result, hooks, session, order = await execute_resume(monkeypatch, request, repo)
    assert result["status"] == "error"
    assert "private-marker" not in str(result)
    assert order == []
    hooks["handle_failure"].assert_not_awaited()
    hooks["persist_chat_turn"].assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_compensation_owns_only_the_new_charge_not_the_previous_debit(monkeypatch):
    request, _, _, _, envelope = prepared_fixture()
    result, hooks, session, _ = await execute_resume(
        monkeypatch,
        request,
        repository(envelope),
        fail_persistence=True,
    )
    assert result["status"] == "error"
    assert hooks["handle_failure"].await_args.kwargs["charged_credits"] == 2
    hooks["publish_committed_turn"].assert_not_awaited()
    session.rollback.assert_awaited_once()
    assert "private-persistence-marker" not in str(result)


@pytest.mark.asyncio
async def test_early_settlement_failure_retains_receipts_and_replay_displays_existing_charge(
    monkeypatch,
):
    from service.services.chat.infrastructure.chat_worker.results.accepted import accepted_turn

    request, _, usage, _, envelope = prepared_fixture()
    accepted = accepted_turn(
        job_id=request.job_id,
        owner_id=request.user_id,
        thread_id=request.thread_id,
        reply=envelope["body"]["reply"],
        model=envelope["body"]["model"],
        usage=usage,
    )
    payload = {
        "thread_id": request.thread_id,
        CHECKPOINT_KEY: envelope,
        ACCEPTED_KEY: accepted.payload(),
    }
    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(
            return_value={
                "status": ProcessingStatus.PROCESSING,
                "payload": payload,
            }
        )
    )
    failed, hooks, session, order = await execute_resume(
        monkeypatch,
        request,
        repo,
        fail_persistence=True,
    )
    assert failed["status"] == "error" and failed["status_code"] == 503
    assert order == ["charge"]
    hooks["handle_failure"].assert_not_awaited()
    hooks["update_job_status"].assert_not_awaited()
    session.rollback.assert_awaited_once()
    assert payload[CHECKPOINT_KEY]["body"]["usage"] == usage
    assert "private-persistence-marker" not in repr(failed)
    replay, hooks, _, order = await execute_resume(
        monkeypatch,
        request,
        repo,
        settled_credits=12,
        charge_credits=0,
    )
    assert replay["status"] == "success"
    assert replay["metadata"]["usage"]["credits"] == 12
    assert order == ["charge", "persist", "terminal", "commit", "publish"]
    hooks["handle_failure"].assert_not_awaited()


@pytest.mark.asyncio
async def test_corrupt_early_receipts_cannot_authorize_prepared_settlement(monkeypatch):
    from service.services.chat.infrastructure.chat_worker.results.accepted import accepted_turn

    request, _, usage, _, envelope = prepared_fixture()
    mismatched = accepted_turn(
        job_id=request.job_id,
        owner_id=request.user_id,
        thread_id=request.thread_id,
        reply="other canonical reply",
        model=envelope["body"]["model"],
        usage=usage,
    )
    repo = repository(envelope)
    repo.lock_prepared_turn.return_value["payload"][ACCEPTED_KEY] = mismatched.payload()
    result, hooks, _, order = await execute_resume(monkeypatch, request, repo)
    assert result["status"] == "error" and result["status_code"] == 503
    assert order == []
    hooks["handle_failure"].assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_origin", [False, True])
async def test_resume_keeps_publication_intent_private_and_enqueues_once(
    monkeypatch, missing_origin
):
    request, private, usage, public, _ = prepared_fixture()
    private["workspace_id"] = "ws-synthetic"
    private["expires_at"] = time.time() + 600
    descriptor = {
        "build_id": "private-build-marker",
        "artifact_id": "private-artifact-marker",
        "role": "pdf",
        "source_digest": "a" * 64,
        "artifact_sha256": "b" * 64,
        "artifact_size": 1,
        "filename": "sample.pdf",
        "mime_type": "application/pdf",
        "initial_status": "pending_delivery",
    }
    private["publications"] = [descriptor]
    envelope = PreparedTurnCheckpoint.create(
        job_id=request.job_id,
        owner_id=request.user_id,
        thread_id=request.thread_id,
        reply="accepted",
        model="synthetic",
        metadata={"public": public, "private": private},
        usage=usage,
    ).payload()
    enqueue = AsyncMock(
        side_effect=ValueError("publication_message_missing") if missing_origin else None
    )
    trigger = Mock()
    monkeypatch.setattr("service.services.chat.persistence.documents.publication.enqueue", enqueue)
    monkeypatch.setattr(
        "service.infrastructure.messaging.tasks.deliver_document_publications.delay", trigger
    )
    result, hooks, session, _ = await execute_resume(monkeypatch, request, repository(envelope))
    assert result["status"] == ("error" if missing_origin else "success")
    enqueue.assert_awaited_once()
    assert enqueue.await_args.kwargs["descriptors"] == (descriptor,)
    assert enqueue.await_args.kwargs["workspace_id"] == "ws-synthetic"
    origin = hooks["persist_chat_turn"].await_args.kwargs["assistant_message_id"]
    assert enqueue.await_args.kwargs["origin_message_id"] == origin
    from uuid import NAMESPACE_URL, uuid5

    assert origin == str(uuid5(NAMESPACE_URL, f"chat-document-message:{request.job_id}"))
    if missing_origin:
        trigger.assert_not_called()
        hooks["publish_committed_turn"].assert_not_awaited()
        session.rollback.assert_awaited_once()
        assert hooks["handle_failure"].await_args.kwargs["charged_credits"] == 2
        assert "private-build-marker" not in repr(result)
        return
    trigger.assert_called_once()
    persisted = hooks["persist_chat_turn"].await_args.kwargs["assistant_metadata"]
    published = hooks["publish_committed_turn"].await_args.kwargs["metadata"]
    assert "private-build-marker" not in json.dumps([persisted, published, result])
    assert "private-artifact-marker" not in json.dumps([persisted, published, result])


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["digest", "reservation", "lookup", "terminal", "usage"])
async def test_restore_failure_never_executes_compensates_or_relabels(monkeypatch, fault, caplog):
    request, private, usage, public, envelope = prepared_fixture()
    repo = repository(envelope)
    if fault == "digest":
        envelope["sha256"] = "invalid-private-marker"
    elif fault == "reservation":
        private["reserved_estimate"] = -1
        envelope = PreparedTurnCheckpoint.create(
            job_id=request.job_id,
            owner_id=request.user_id,
            thread_id=request.thread_id,
            reply="accepted",
            model="synthetic",
            metadata={"public": public, "private": private},
            usage=usage,
        ).payload()
        repo = repository(envelope)
    elif fault == "lookup":
        repo.lock_prepared_turn.side_effect = RuntimeError("private-database-body-marker")
    elif fault == "terminal":
        repo = repository(envelope, status=ProcessingStatus.SUCCESS)
    else:
        usage["total_tokens"] = "private-usage-marker"
        envelope = PreparedTurnCheckpoint.create(
            job_id=request.job_id,
            owner_id=request.user_id,
            thread_id=request.thread_id,
            reply="accepted",
            model="synthetic",
            metadata={"public": public, "private": private},
            usage=usage,
        ).payload()
        repo = repository(envelope)
    result, hooks, session, order = await execute_resume(monkeypatch, request, repo)
    assert result["status"] == "error" and result["status_code"] == 503
    assert order == []
    hooks["handle_failure"].assert_not_awaited()
    hooks["persist_chat_turn"].assert_not_awaited()
    hooks["update_job_status"].assert_not_awaited()
    session.rollback.assert_awaited_once()
    assert "private-marker" not in str(result) + caplog.text
    assert "private-database-body-marker" not in str(result) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [ProcessingStatus.SUCCESS, ProcessingStatus.FAILURE])
@pytest.mark.parametrize("reinjected", [False, True])
async def test_terminal_transition_removes_both_private_checkpoints(status, reinjected):
    job = SimpleNamespace(
        status=ProcessingStatus.PROCESSING,
        payload={
            CHECKPOINT_KEY: {"private": "prepared"},
            ACCEPTED_KEY: {"private": "accepted"},
            "_materialization_plan_v1": {"private": "materialization"},
            "thread_id": "thread",
        },
    )
    repo = SimpleNamespace(
        fetch_job_by_id=AsyncMock(return_value=job), update_job_status=AsyncMock()
    )
    result = {"reply": "accepted"}
    if reinjected:
        result.update({CHECKPOINT_KEY: {}, ACCEPTED_KEY: {}, "_materialization_plan_v1": {}})
    session = AsyncMock()
    await job_state.update_job_status(
        repo,
        str(uuid4()),
        status,
        session,
        str(uuid4()),
        result,
    )
    assert job.payload == {"thread_id": "thread", "reply": "accepted"}
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonterminal_update_preserves_both_recovery_checkpoints():
    original = {
        CHECKPOINT_KEY: {"private": "prepared"},
        ACCEPTED_KEY: {"private": "accepted"},
        "thread_id": "thread",
    }
    job = SimpleNamespace(status=ProcessingStatus.PROCESSING, payload=original)
    repo = SimpleNamespace(
        fetch_job_by_id=AsyncMock(return_value=job), update_job_status=AsyncMock()
    )
    await job_state.update_job_status(
        repo, str(uuid4()), ProcessingStatus.PROCESSING, AsyncMock(), str(uuid4())
    )
    assert job.payload == original
