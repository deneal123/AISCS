"""Cancellation may settle the current stopped owner, never authorize more execution."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.harness import cancellation, recovery


def context(cancelled=True):
    request = SimpleNamespace(job_id=str(uuid4()), user_id=str(uuid4()), thread_id=str(uuid4()))
    state = SimpleNamespace(
        harness_task_id=request.job_id,
        execution_attempt_id=str(uuid4()),
        harness_epoch=2,
        cancelled_execution=cancelled,
    )
    return request, state


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_finalization_requires_same_attempt_and_exact_stop_state(cancelled):
    request, state = context(cancelled)
    from uuid import UUID

    session = SimpleNamespace(scalar=AsyncMock(return_value=UUID(state.harness_task_id)))
    await recovery.verify_harness_attempt(session, request, state)
    query, parameters = session.scalar.call_args.args
    assert parameters["cancelled"] is cancelled
    assert parameters["epoch"] == 2
    assert "CASE WHEN :cancelled THEN 'true' ELSE 'false' END" in str(query)
    assert "j.status='PROCESSING'" in str(query) and "FOR UPDATE OF t,j" in str(query)


@pytest.mark.asyncio
async def test_model_projection_cannot_authorize_the_stopped_owner_path():
    request, state = context(False)
    session = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(JobStateUnavailable, match="cancellation fenced"):
        await cancellation.cancelled_projection(session, request, state)
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_fenced_cancelled_owner_does_not_project_or_settle():
    request, state = context()
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: None))
        )
    )
    with pytest.raises(JobStateUnavailable, match="cancellation fenced"):
        await cancellation.cancelled_projection(session, request, state)
    query, parameters = session.execute.call_args.args
    for clause in [
        "t.user_id=:owner",
        "t.thread_id=:thread",
        "t.execution_attempt_id=:attempt",
        "t.fencing_epoch=:epoch",
        "j.payload->>'_cancel_requested_v1'='true'",
    ]:
        assert clause in str(query)
    assert parameters["epoch"] == state.harness_epoch


@pytest.mark.asyncio
async def test_cancelled_projection_is_the_existing_backend_verifier_result(monkeypatch):
    request, state = context()
    row = {"task_id": request.job_id}
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))
        )
    )
    expected = {
        "schema_version": 2,
        "status": "cancelled",
        "verified": False,
        "blocker": "cancelled",
        "confirmed": [],
        "unchecked": ["verify_project"],
        "references": [],
        "rounds": 4,
        "repair_cycles": 0,
    }
    snapshot = object()
    monkeypatch.setattr(cancellation, "snapshot", AsyncMock(return_value=snapshot))
    read = AsyncMock(return_value=expected)
    monkeypatch.setattr(cancellation, "read_result", read)
    assert await cancellation.cancelled_projection(session, request, state) == expected
    read.assert_awaited_once_with(session, row, snapshot)


@pytest.mark.asyncio
async def test_received_cancelled_terminal_cannot_bypass_the_durable_stop_fence():
    request, state = context(False)
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: None))
        )
    )
    with pytest.raises(JobStateUnavailable, match="cancellation fenced"):
        await cancellation.cancelled_projection(session, request, state, terminal_cancelled=True)
    assert state.cancelled_execution is False


@pytest.mark.asyncio
async def test_cancelled_terminal_race_is_regrounded_before_fence_exception(monkeypatch):
    request, state = context(False)
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                mappings=lambda: SimpleNamespace(first=lambda: {"task_id": request.job_id})
            )
        )
    )
    expected = {
        "schema_version": 2,
        "status": "cancelled",
        "verified": False,
        "blocker": "cancelled",
        "confirmed": [],
        "unchecked": ["verify_project"],
        "references": [],
        "rounds": 4,
        "repair_cycles": 0,
    }
    monkeypatch.setattr(cancellation, "snapshot", AsyncMock(return_value=object()))
    monkeypatch.setattr(cancellation, "read_result", AsyncMock(return_value=expected))
    assert (
        await cancellation.cancelled_projection(session, request, state, terminal_cancelled=True)
        == expected
    )
    assert state.cancelled_execution is True


@pytest.mark.asyncio
async def test_cancelled_resume_restores_only_the_exact_accounted_attempt(monkeypatch):
    from service.services.chat.infrastructure.chat_worker.harness import cancelled_restore

    request, state = context()
    state.harness_task_id = None
    task = str(uuid4())
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                mappings=lambda: SimpleNamespace(first=lambda: {"fencing_epoch": 7})
            )
        )
    )
    projection = {"status": "cancelled"}
    apply = AsyncMock(return_value=projection)
    monkeypatch.setattr(cancelled_restore, "cancelled_projection", apply)
    assert (
        await cancelled_restore.restored_cancellation(
            session, request, state, {"_harness_task_v1": task}
        )
        == projection
    )
    assert state.harness_task_id == task and state.harness_epoch == 7
    query, values = session.execute.call_args.args
    assert str(values["attempt"]) == state.execution_attempt_id
    assert "execution_attempt_id=:attempt" in str(query)
    apply.assert_awaited_once_with(session, request, state)


@pytest.mark.asyncio
async def test_cancelled_resume_cannot_adopt_another_owner(monkeypatch):
    from service.services.chat.infrastructure.chat_worker.harness import cancelled_restore

    request, state = context()
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: None))
        )
    )
    project = AsyncMock()
    monkeypatch.setattr(cancelled_restore, "cancelled_projection", project)
    with pytest.raises(JobStateUnavailable, match="identity unavailable"):
        await cancelled_restore.restored_cancellation(
            session, request, state, {"_harness_task_v1": str(uuid4())}
        )
    project.assert_not_awaited()
