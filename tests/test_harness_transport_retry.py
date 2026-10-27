"""Повтор доставки требует commit, нового attempt и прежнего общего бюджета."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.harness.interruption import (
    recover_interrupted_run,
    retry_delivery,
)
from service.services.chat.persistence.harness.retry import (
    RETRY_KEY,
    HarnessRetryRepository,
    next_retry,
)
from service.services.chat.persistence.harness.state import require_active
from service.shared.harness_protocol import HarnessFailure


def test_transport_retries_are_bounded_and_idempotent_per_attempt():
    previous = None
    for count in range(1, 4):
        attempt = str(uuid4())
        previous = next_retry(previous, attempt)
        assert previous == {"attempt_id": attempt, "count": count, "state": "pending"}
        assert next_retry(previous, attempt) == previous
    blocked = next_retry(previous, str(uuid4()))
    assert blocked["state"] == "blocked" and blocked["count"] == 3
    assert next_retry(blocked, str(uuid4())) == blocked


@pytest.mark.parametrize(
    "bad", [[], {}, {"attempt_id": "not-an-id", "count": 1, "state": "pending"}]
)
def test_invalid_counter_does_not_admit_recovery(bad):
    with pytest.raises(HarnessFailure):
        next_retry(bad, str(uuid4()))


@pytest.mark.parametrize("state", ["pending", "blocked"])
def test_recovery_marker_fences_old_dispatch_but_not_rebound_owner(state):
    attempt = str(uuid4())
    row = {
        "job_status": "PROCESSING",
        "execution_attempt_id": attempt,
        "job_payload": {RETRY_KEY: {"attempt_id": attempt, "count": 1, "state": state}},
    }
    with pytest.raises(HarnessFailure, match="harness_fenced"):
        require_active(row)
    row["execution_attempt_id"] = str(uuid4())
    if state == "pending":
        require_active(row)
    else:
        with pytest.raises(HarnessFailure):
            require_active(row)


def repository_fixture(*, commit_error=False, missing=False):
    task, job, user, thread, attempt = (str(uuid4()) for _ in range(5))
    row = {"task_id": task, "job_payload": {"preserved": "private"}}
    calls = []

    async def execute(sql, params):
        calls.append((str(sql), params))
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(first=lambda: None if missing else row)
        )

    db = SimpleNamespace(execute=AsyncMock(side_effect=execute), commit=AsyncMock())
    if commit_error:
        db.commit.side_effect = ConnectionError("PRIVATE_ACK")

    @asynccontextmanager
    async def session():
        yield db

    repo = HarnessRetryRepository(SimpleNamespace(get_session_context=session))
    params = dict(
        task_id=task, job_id=job, user_id=user, thread_id=thread, attempt_id=attempt, epoch=4
    )
    return repo, db, calls, params


@pytest.mark.asyncio
async def test_retry_commits_the_same_job_intent_before_returning_permission():
    repo, db, calls, params = repository_fixture()
    decision, result = await repo.prepare(**params)
    assert decision == {"attempt_id": params["attempt_id"], "count": 1, "state": "pending"}
    assert result is None
    db.commit.assert_awaited_once()
    query = calls[0][0]
    for invariant in (
        "FOR UPDATE OF t,j",
        "fencing_epoch=:epoch",
        "_cancel_requested_v1",
        "_accepted_turn_v1",
        "profile.chat_threads",
        "_execution_attempt_v1",
    ):
        assert invariant in query
    saved = json.loads(calls[1][1]["body"])
    assert saved["preserved"] == "private" and saved[RETRY_KEY] == decision
    assert not any("harness_grant" in sql or "token_reservations" in sql for sql, _ in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown_ack", "fenced"])
async def test_unconfirmed_retry_never_returns_dispatch_permission(failure):
    repo, db, calls, params = repository_fixture(
        commit_error=failure == "unknown_ack", missing=failure == "fenced"
    )
    with pytest.raises(HarnessFailure) as error:
        await repo.prepare(**params)
    assert "PRIVATE" not in str(error.value)
    if failure == "fenced":
        db.commit.assert_not_awaited()
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_interruption_does_not_schedule_retry_after_unknown_checkpoint_ack(monkeypatch):
    from service.services.chat.infrastructure.chat_worker.harness import interruption

    prepare = AsyncMock(side_effect=HarnessFailure())
    monkeypatch.setattr(interruption.HarnessRetryRepository, "prepare", prepare)
    session = SimpleNamespace(rollback=AsyncMock())
    publisher = SimpleNamespace(publish_payload=Mock())
    request = SimpleNamespace(
        celery_task_id=str(uuid4()),
        job_id=str(uuid4()),
        user_id=str(uuid4()),
        thread_id=str(uuid4()),
    )
    state = SimpleNamespace(
        harness_task_id=str(uuid4()), execution_attempt_id=str(uuid4()), harness_epoch=2
    )
    result = await recover_interrupted_run(
        connector=object(), session=session, request=request, state=state, publisher=publisher
    )
    assert result["status"] == "error"
    task = SimpleNamespace(retry=Mock())
    assert retry_delivery(task, result) == result
    task.retry.assert_not_called()


@pytest.mark.parametrize("count,delay", [(1, 3), (2, 9), (3, 27)])
def test_celery_retries_the_same_delivery_only_for_acknowledged_pending_marker(count, delay):
    class Retry(Exception):
        pass

    task = SimpleNamespace(retry=Mock(side_effect=Retry()))
    with pytest.raises(Retry):
        retry_delivery(task, {"status": "recovery_pending", "recovery_retry_count": count})
    task.retry.assert_called_once_with(countdown=delay, max_retries=3)
    task.retry.reset_mock()
    result = {"status": "processing"}
    assert retry_delivery(task, result) == result
    task.retry.assert_not_called()


@pytest.mark.parametrize("count", [None, True, 0, 4, "1", 1.0])
def test_retry_delay_requires_the_committed_task_counter(count):
    task = SimpleNamespace(retry=Mock())
    with pytest.raises(HarnessFailure):
        retry_delivery(task, {"status": "recovery_pending", "recovery_retry_count": count})
    task.retry.assert_not_called()


@pytest.mark.asyncio
async def test_committed_retry_counter_is_private_and_survives_worker_request_counter(monkeypatch):
    from service.services.chat.infrastructure.chat_worker.harness import interruption

    monkeypatch.setattr(
        interruption.HarnessRetryRepository,
        "prepare",
        AsyncMock(return_value=({"state": "pending", "count": 2}, None)),
    )
    publisher = SimpleNamespace(publish_payload=Mock())
    request = SimpleNamespace(
        celery_task_id=str(uuid4()),
        job_id=str(uuid4()),
        user_id=str(uuid4()),
        thread_id=str(uuid4()),
    )
    state = SimpleNamespace(
        harness_task_id=str(uuid4()), execution_attempt_id=str(uuid4()), harness_epoch=2
    )
    result = await recover_interrupted_run(
        connector=object(),
        session=SimpleNamespace(rollback=AsyncMock()),
        request=request,
        state=state,
        publisher=publisher,
    )
    assert result["recovery_retry_count"] == 2
    assert "recovery_retry_count" not in publisher.publish_payload.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", [None, "cost_unknown", "operation_unknown"])
async def test_exhaustion_projects_blocked_without_hiding_uncertainty_or_confirmed_evidence(
    monkeypatch, blocker
):
    from service.services.chat.persistence.harness import result as projection

    confirmed = {
        "schema_version": 2,
        "status": "completed" if blocker is None else "partial",
        "verified": blocker is None,
        "blocker": blocker,
        "confirmed": ["write_file"],
        "unchecked": [],
        "references": [{"criterion_id": "write_file"}],
        "rounds": 5,
        "repair_cycles": 1,
    }
    monkeypatch.setattr(projection, "task_result", lambda *_args: dict(confirmed))
    db = SimpleNamespace(scalar=AsyncMock(return_value=blocker == "operation_unknown"))
    row = {"task_id": uuid4(), "job_payload": {RETRY_KEY: {"state": "blocked"}}}
    result = await projection.read_result(db, row, object())
    assert result["status"] == "blocked" and result["verified"] is False
    assert result["blocker"] == (blocker or "checkpoint_unavailable")
    for key in ("confirmed", "unchecked", "references", "rounds", "repair_cycles"):
        assert result[key] == confirmed[key]


@pytest.mark.asyncio
async def test_recovered_harness_uses_saved_context_without_another_memory_model_call(monkeypatch):
    from service.services.chat.infrastructure.chat_worker.execution import run
    from service.services.chat.infrastructure.chat_worker.run_contracts import (
        MutableRunState,
        WorkerRunRequest,
    )
    from service.services.chat.infrastructure.context import summary

    memory = AsyncMock(side_effect=AssertionError("memory retrieval must not repeat"))
    monkeypatch.setattr(run, "load_memory_parts", memory)
    monkeypatch.setattr(run, "load_history_items", AsyncMock(return_value=[]))
    monkeypatch.setattr(run, "resolve_history_limit", AsyncMock(return_value=8))
    monkeypatch.setattr(run, "owner_checked_attachments", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        run,
        "collect_engine_inputs",
        AsyncMock(
            return_value=SimpleNamespace(
                engine_env={},
                tabular_files=[],
                reference_image_url=None,
                has_non_tabular_attachment=False,
                repo_graph_ids=[],
            )
        ),
    )
    monkeypatch.setattr(summary, "summarized_history", AsyncMock(return_value=("", [])))
    request = WorkerRunRequest(
        job_id=str(uuid4()),
        user_id=str(uuid4()),
        thread_id=str(uuid4()),
        text="Продолжить",
        memory_enabled=True,
    )
    hooks = SimpleNamespace(
        recall_thread_file=AsyncMock(return_value=""),
        resolve_persona_switched=AsyncMock(return_value=False),
    )
    prepared = await run._prepare_context(
        request,
        config=object(),
        pg_connector=object(),
        redis_client=object(),
        session=object(),
        pseudo_session=object(),
        publisher=Mock(),
        state=MutableRunState(harness_recovered=True),
        hooks=hooks,
        file_service=object(),
    )
    assert prepared.memory_parts == ("", "")
    memory.assert_not_awaited()
