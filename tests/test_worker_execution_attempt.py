"""A lost live lock must not authorize another provider invocation for one job."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.execution import run as run_execution
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)
from service.services.jobs.persistence.transitions import EXECUTION_KEY, guarded_payload
from service.shared.repositories.exceptions import RepositoryError


@pytest.mark.asyncio
async def test_new_delivery_without_terminal_cannot_reinvoke_started_execution(monkeypatch):
    started = False

    async def claim(*_args, **_kwargs):
        nonlocal started
        if started:
            return False
        started = True
        return True

    repository = SimpleNamespace(claim_chat_execution=claim)
    session = AsyncMock()
    execute = AsyncMock(return_value={"reply": "synthetic"})
    reserve = AsyncMock(return_value=(object(), None))
    monkeypatch.setattr(run_execution, "_reserve_run", reserve)
    monkeypatch.setattr(run_execution, "stage_execution_accounting", AsyncMock())
    monkeypatch.setattr(run_execution, "_prepare_context", AsyncMock(return_value=object()))
    monkeypatch.setattr(run_execution, "_execute_agent", execute)
    request = WorkerRunRequest(str(uuid4()), str(uuid4()), "synthetic", str(uuid4()))
    args = {
        "config": None,
        "pg_connector": None,
        "redis_client": None,
        "publisher": Mock(),
        "job_repo": repository,
        "file_service": None,
        "session": session,
        "hooks": SimpleNamespace(prepared_results=None),
        "agent_execution": None,
    }
    await run_execution._run_or_restore(request, state=MutableRunState(), **args)
    with pytest.raises(JobStateUnavailable):
        await run_execution._run_or_restore(request, state=MutableRunState(), **args)
    assert execute.await_count == 1
    assert reserve.await_count == 1
    # First delivery commits admission and preflight; redelivery commits neither.
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_uncertain_execution_claim_commit_never_invokes_provider(monkeypatch):
    repository = SimpleNamespace(claim_chat_execution=AsyncMock(return_value=True))
    session = AsyncMock()
    session.commit.side_effect = RuntimeError("PRIVATE_COMMIT_ACK")
    reserve = AsyncMock(return_value=(object(), None))
    execute = AsyncMock()
    monkeypatch.setattr(run_execution, "_reserve_run", reserve)
    monkeypatch.setattr(run_execution, "_prepare_context", AsyncMock(return_value=object()))
    monkeypatch.setattr(run_execution, "_execute_agent", execute)
    request = WorkerRunRequest(str(uuid4()), str(uuid4()), "synthetic", str(uuid4()))
    with pytest.raises(JobStateUnavailable) as error:
        await run_execution._run_or_restore(
            request,
            config=None,
            pg_connector=None,
            redis_client=None,
            publisher=Mock(),
            job_repo=repository,
            file_service=None,
            session=session,
            state=MutableRunState(),
            hooks=SimpleNamespace(prepared_results=None),
            agent_execution=None,
        )
    assert "PRIVATE_COMMIT_ACK" not in str(error.value)
    reserve.assert_not_awaited()
    execute.assert_not_awaited()


@pytest.mark.parametrize(
    "status", [ProcessingStatus.PROCESSING, ProcessingStatus.SUCCESS, ProcessingStatus.FAILURE]
)
def test_execution_attempt_survives_whole_payload_updates(status):
    marker = str(uuid4())
    result = guarded_payload(
        ProcessingStatus.PROCESSING,
        {EXECUTION_KEY: marker, "thread_id": "synthetic"},
        status,
        {"reply": "synthetic"},
        None,
    )
    assert result[EXECUTION_KEY] == marker


@pytest.mark.parametrize("stored", [{}, {EXECUTION_KEY: str(uuid4())}])
def test_whole_payload_update_cannot_create_or_replace_execution_attempt(stored):
    with pytest.raises(RepositoryError):
        guarded_payload(
            ProcessingStatus.PROCESSING,
            stored,
            ProcessingStatus.PROCESSING,
            {EXECUTION_KEY: str(uuid4())},
            None,
        )


@pytest.mark.asyncio
async def test_canonical_restore_precedes_attempt_admission(monkeypatch):
    async def restore(*_args, state, **_kwargs):
        state.restored_result = {
            "usage": {},
            "reply": "accepted",
            "metadata": {},
            "resolved_model": "synthetic",
        }
        return True

    repository = SimpleNamespace(claim_chat_execution=AsyncMock())
    reserve = AsyncMock()
    execute = AsyncMock()
    monkeypatch.setattr(run_execution, "_reserve_run", reserve)
    monkeypatch.setattr(run_execution, "_execute_agent", execute)
    request = WorkerRunRequest(str(uuid4()), str(uuid4()), "synthetic", str(uuid4()))
    result, prepared, refusal = await run_execution._run_or_restore(
        request,
        config=None,
        pg_connector=None,
        redis_client=None,
        publisher=Mock(),
        job_repo=repository,
        file_service=None,
        session=AsyncMock(),
        state=MutableRunState(),
        hooks=SimpleNamespace(
            prepared_results=SimpleNamespace(restore=restore), record_catalog_events=Mock()
        ),
        agent_execution=None,
    )
    assert result["reply"] == "accepted" and prepared is None and refusal is None
    repository.claim_chat_execution.assert_not_awaited()
    reserve.assert_not_awaited()
    execute.assert_not_awaited()
