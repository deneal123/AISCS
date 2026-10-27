"""An unverified job must not be replayed or relabelled during a DB outage."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.services.chat.domain.chat_exceptions import JobServiceUnavailableError
from service.services.chat.infrastructure.chat_worker.execution import job_state
from service.services.chat.infrastructure.chat_worker.execution import run as run_execution
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    WorkerExecutionHooks,
    WorkerRunRequest,
)


class BrokenJobRepository:
    def __init__(self, *_args):
        pass

    async def fetch_job_by_id(self, *_args, **_kwargs):
        raise RuntimeError("private-database-body-marker")


@pytest.mark.asyncio
async def test_unavailable_redelivery_lookup_is_not_a_fresh_job():
    with pytest.raises(JobServiceUnavailableError):
        await job_state.redelivery_short_circuit(
            BrokenJobRepository(), str(uuid4()), AsyncMock(), str(uuid4())
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("publish_fails", [False, True])
@pytest.mark.parametrize("rollback_fails", [False, True])
async def test_worker_lookup_outage_never_executes_or_overwrites_terminal(
    monkeypatch, caplog, publish_fails, rollback_fails
):
    session = AsyncMock()
    session.scalar.return_value = True
    if rollback_fails:
        session.rollback.side_effect = RuntimeError("private-rollback-marker")

    @asynccontextmanager
    async def transaction():
        yield session

    publisher = Mock()
    if publish_fails:
        publisher.publish_payload.side_effect = RuntimeError("private-transport-marker")
    hooks = {field: AsyncMock() for field in WorkerExecutionHooks.__dataclass_fields__}
    hooks.update(
        prepared_results=None,
        bind_runtime_settings=Mock(),
        publisher_factory=Mock(return_value=publisher),
        build_file_service=Mock(return_value=object()),
        redelivery_short_circuit=job_state.redelivery_short_circuit,
    )
    monkeypatch.setattr(
        "service.services.jobs.persistence.job_repository.JobRepository", BrokenJobRepository
    )
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
    for field in (
        "reserve_credits",
        "update_job_status",
        "run_with_cancel",
        "handle_failure",
        "charge_and_describe",
        "persist_chat_turn",
    ):
        hooks[field].assert_not_awaited()
    session.rollback.assert_awaited_once()
    publisher.close.assert_called_once()
    assert "private-database-body-marker" not in str(result) + caplog.text
    assert "private-transport-marker" not in str(result) + caplog.text
    assert "private-rollback-marker" not in str(result) + caplog.text


@pytest.mark.asyncio
async def test_storage_initialization_failure_uses_terminal_seam_before_model(monkeypatch):
    from service.composition.storage import StorageConfigurationError

    session = AsyncMock()
    session.scalar.return_value = True

    @asynccontextmanager
    async def transaction():
        yield session

    publisher = Mock()
    hooks = {field: AsyncMock() for field in WorkerExecutionHooks.__dataclass_fields__}
    hooks.update(
        prepared_results=None,
        bind_runtime_settings=Mock(),
        publisher_factory=Mock(return_value=publisher),
        build_file_service=Mock(side_effect=StorageConfigurationError("storage_init_failed")),
        redelivery_short_circuit=AsyncMock(return_value=None),
    )
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
    hooks["handle_failure"].assert_awaited_once()
    hooks["run_with_cancel"].assert_not_awaited()
    hooks["charge_and_describe"].assert_not_awaited()
    session.rollback.assert_awaited_once()
    publisher.close.assert_called_once()
