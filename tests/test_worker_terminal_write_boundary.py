"""A failed terminal latch must never be presented as durable success."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.domain.chat_exceptions import JobServiceUnavailableError
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import (
    JournalReceipt,
    UsageJournal,
)
from service.services.chat.infrastructure.chat_worker.execution import job_state
from service.services.chat.infrastructure.chat_worker.execution import run as run_execution
from service.services.chat.infrastructure.chat_worker.phases import RunPhase
from service.services.chat.infrastructure.chat_worker.results import (
    preparation as result_preparation,
)
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerExecutionHooks,
    WorkerRunRequest,
)


def broken_repository(stage):
    job = SimpleNamespace(status=ProcessingStatus.PROCESSING, payload={})
    repository = SimpleNamespace(
        fetch_job_by_id=AsyncMock(return_value=job),
        update_job_status=AsyncMock(),
    )
    target = repository.fetch_job_by_id if stage == "lookup" else repository.update_job_status
    target.side_effect = RuntimeError("private-terminal-storage-marker")
    return repository


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["lookup", "write"])
async def test_terminal_write_failure_is_explicit_and_bounded(stage, caplog):
    with pytest.raises(JobServiceUnavailableError) as caught:
        await job_state.update_job_status(
            broken_repository(stage),
            str(uuid4()),
            ProcessingStatus.SUCCESS,
            AsyncMock(),
            str(uuid4()),
            {"reply": "synthetic"},
        )
    assert "private-terminal-storage-marker" not in str(caught.value) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("journal_mismatch", [False, True])
async def test_terminal_latch_failure_blocks_commit_and_success_publication(
    monkeypatch, journal_mismatch
):
    session = AsyncMock()
    request = WorkerRunRequest(str(uuid4()), str(uuid4()), "synthetic", str(uuid4()))
    state = MutableRunState()
    state.phase.advance(RunPhase.RESERVED)
    state.phase.advance(RunPhase.EXECUTING)
    if journal_mismatch:
        state.usage_journal = UsageJournal(
            str(uuid4()), 1, (JournalReceipt("call", "openai", "synthetic", None, 2, 1, False),)
        )
    hooks = SimpleNamespace(
        prepared_results=None,
        reply_or_provider_failure=Mock(return_value=("synthetic", {})),
        record_catalog_events=AsyncMock(),
        charge_and_describe=AsyncMock(return_value=(1, {})),
        persist_chat_turn=AsyncMock(),
        update_job_status=job_state.update_job_status,
        publish_committed_turn=AsyncMock(),
        extract_memory=AsyncMock(),
    )
    monkeypatch.setattr(
        result_preparation, "persist_all_artifacts", AsyncMock(return_value=(None, {}))
    )
    with pytest.raises(JobServiceUnavailableError):
        await run_execution._finalize_success(
            request,
            {"resolved_model": "synthetic", "reply_parts_count": 1, "reply_chars_count": 9},
            SimpleNamespace(workflow_observations=[], workflow_executions=[]),
            config=object(),
            pg_connector=object(),
            redis_client=None,
            publisher=Mock(),
            job_repo=broken_repository("write"),
            file_service=object(),
            session=session,
            state=state,
            hooks=hooks,
            started_at=0,
        )
    session.commit.assert_not_awaited()
    hooks.publish_committed_turn.assert_not_awaited()
    if journal_mismatch:
        hooks.charge_and_describe.assert_not_awaited()
        hooks.persist_chat_turn.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint_failure", [False, True])
async def test_write_outage_uses_rollback_and_charge_compensation(
    monkeypatch, caplog, checkpoint_failure
):
    session = AsyncMock()
    session.scalar.return_value = True

    @asynccontextmanager
    async def transaction():
        yield session

    async def reserve(_request, *, state, **_kwargs):
        state.phase.advance(RunPhase.RESERVED)
        return object(), None

    async def execute(_request, _prepared, *, state, **_kwargs):
        state.phase.advance(RunPhase.EXECUTING)
        return {"resolved_model": "synthetic", "reply_parts_count": 1, "reply_chars_count": 9}

    publisher = Mock()
    hooks = {field: AsyncMock() for field in WorkerExecutionHooks.__dataclass_fields__}
    hooks.update(
        prepared_results=None,
        bind_runtime_settings=Mock(),
        publisher_factory=Mock(return_value=publisher),
        build_file_service=Mock(return_value=object()),
        redelivery_short_circuit=AsyncMock(return_value=None),
        update_job_status=job_state.update_job_status,
        reply_or_provider_failure=Mock(return_value=("synthetic", {})),
        charge_and_describe=AsyncMock(return_value=(1, {})),
    )
    repository = broken_repository("write")
    repository.claim_chat_execution = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "service.services.jobs.persistence.job_repository.JobRepository",
        lambda _connector: repository,
    )
    monkeypatch.setattr(run_execution, "_reserve_run", reserve)
    monkeypatch.setattr(run_execution, "stage_execution_accounting", AsyncMock())
    monkeypatch.setattr(run_execution, "_execute_agent", execute)
    monkeypatch.setattr(
        run_execution,
        "_prepare_context",
        AsyncMock(return_value=SimpleNamespace(workflow_observations=[], workflow_executions=[])),
    )
    monkeypatch.setattr(
        result_preparation, "persist_all_artifacts", AsyncMock(return_value=(None, {}))
    )
    if checkpoint_failure:

        async def interrupted_run(*_args, state, **_kwargs):
            state.usage_checkpoint_observed = True
            raise RuntimeError("private-terminal-storage-marker")

        monkeypatch.setattr(run_execution, "_run_or_restore", interrupted_run)
    result = await run_execution.execute_chat_job(
        WorkerRunRequest(str(uuid4()), str(uuid4()), "synthetic", str(uuid4())),
        hooks=WorkerExecutionHooks(**hooks),
        dependency_factory=SimpleNamespace(
            create_pg_connector=lambda _config: SimpleNamespace(get_session_context=transaction),
            create_redis_client=lambda _config: None,
        ),
        agent_execution=object(),
    )
    assert result["status"] == "error"
    assert result["error_code"] == "job_service_unavailable"
    assert result["status_code"] == 503
    session.rollback.assert_awaited_once()
    # Admission/preflight commit; failed terminal publication does not.
    if checkpoint_failure:
        session.commit.assert_not_awaited()
        hooks["handle_failure"].assert_not_awaited()
    else:
        assert session.commit.await_count == 2
        hooks["handle_failure"].assert_awaited_once()
        assert hooks["handle_failure"].await_args.kwargs["charged_credits"] == 1
    hooks["publish_committed_turn"].assert_not_awaited()
    publisher.close.assert_called_once()
    assert "private-terminal-storage-marker" not in str(result) + caplog.text
