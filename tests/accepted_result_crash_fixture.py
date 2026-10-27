"""Isolated dev task: actual prefork loss, SQL recovery; scripted model/charging/messages."""

import os
import re
import time
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from sqlalchemy import text

from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.messaging.celery_app import celery_app
from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.execution import run as run_execution
from service.services.chat.infrastructure.chat_worker.execution.job_state import update_job_status
from service.services.chat.infrastructure.chat_worker.results.prepared import (
    PreparedResultCoordinator,
)
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerExecutionHooks,
    WorkerRunRequest,
)
from service.services.chat.infrastructure.chat_worker.task_runtime import run_coroutine
from service.services.jobs.persistence.job_repository import JobRepository
from service.settings import Config


async def _run(job_id, marker, first):
    connector = PgConnector(Config().pg)
    store = celery_app.backend.client
    try:
        async with connector.get_session_context() as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT l.user_id,l.payload FROM profile.user_launch l "
                            'JOIN profile."user" u '
                            "ON u.id=l.user_id WHERE l.id=:id AND u.email=:email"
                        ),
                        {"id": UUID(job_id), "email": "s37-e2e-391e5206659a3654@example.com"},
                    )
                )
                .mappings()
                .one()
            )
            assert row["payload"]["fixture_marker"] == marker
            owner = str(row["user_id"])
            request = WorkerRunRequest(job_id, row["payload"]["thread_id"], "synthetic", owner)
            usage = {
                "total_tokens": 3,
                "per_call_usage": [
                    {
                        "call_id": marker.rsplit(":", 1)[1],
                        "provider": "openai",
                        "model": "synthetic",
                        "prompt": 2,
                        "completion": 1,
                    }
                ],
            }
            if first:
                store.incr(marker + ":scripted-acceptances")
                store.expire(marker + ":scripted-acceptances", 600)
                await PreparedResultCoordinator().capture_accepted(
                    request=request,
                    repository=JobRepository(connector),
                    session=session,
                    state=MutableRunState(),
                    execution_result={**usage, "resolved_model": "synthetic"},
                    reply="synthetic accepted result",
                    metadata={"execution_status": "completed"},
                    prepared=SimpleNamespace(workflow_observations=[], workflow_executions=[]),
                    started_at=time.monotonic(),
                )
                return "captured"

        async def forbidden(*args, **kwargs):
            raise AssertionError("model_or_artifact_reexecution")

        async def charge(**kwargs):
            assert kwargs["execution_result"]["per_call_usage"] == usage["per_call_usage"]
            store.incr(marker + ":settlements")
            store.expire(marker + ":settlements", 600)
            return 0, {**kwargs["metadata"], "usage": {"credits": 0}}

        async def persist(**kwargs):
            assert kwargs["assistant_text"] == "synthetic accepted result"
            store.incr(marker + ":persist-callbacks")
            store.expire(marker + ":persist-callbacks", 600)

        hooks = {name: AsyncMock() for name in WorkerExecutionHooks.__dataclass_fields__}
        hooks.update(
            prepared_results=PreparedResultCoordinator(),
            bind_runtime_settings=Mock(),
            publisher_factory=Mock(
                return_value=SimpleNamespace(
                    publish_payload=Mock(), publish_error=Mock(), close=Mock()
                )
            ),
            build_file_service=Mock(return_value=object()),
            redelivery_short_circuit=AsyncMock(return_value=None),
            reserve_credits=forbidden,
            run_with_cancel=forbidden,
            handle_failure=forbidden,
            update_job_status=update_job_status,
            charge_and_describe=charge,
            persist_chat_turn=persist,
        )
        # Fail loudly if the production restore entrypoint falls through to new work.
        original = run_execution._execute_agent
        run_execution._execute_agent = forbidden
        try:
            outcome = await run_execution.execute_chat_job(
                request,
                hooks=WorkerExecutionHooks(**hooks),
                dependency_factory=SimpleNamespace(
                    create_pg_connector=lambda _: connector, create_redis_client=lambda _: None
                ),
                agent_execution=object(),
            )
        finally:
            run_execution._execute_agent = original
        assert outcome["status"] == "success"
        async with connector.get_session_context() as session:
            final = (
                (
                    await session.execute(
                        text(
                            "SELECT status,payload FROM profile.user_launch "
                            "WHERE id=:id AND user_id=:owner"
                        ),
                        {"id": UUID(job_id), "owner": UUID(owner)},
                    )
                )
                .mappings()
                .one()
            )
            assert final["status"] == ProcessingStatus.SUCCESS.value
            assert not any(
                key in final["payload"]
                for key in ("_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1")
            )
        return "resumed"
    finally:
        await connector.close()


@celery_app.task(
    bind=True, name="s37.accepted-result-crash", acks_late=True, reject_on_worker_lost=True
)
def accepted_with_crash(self, job_id, marker):
    assert re.fullmatch(r"s37:accepted:[0-9a-f]{32}", marker)
    UUID(job_id)
    store = celery_app.backend.client
    attempt = store.incr(marker)
    store.expire(marker, 600)
    assert attempt <= 2
    try:
        outcome = run_coroutine(_run(job_id, marker, attempt == 1))
    except Exception as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        own = [frame.lineno for frame in frames if frame.filename == __file__]
        store.set(marker + ":failure-line", own[-1] if own else 0, ex=600)
        raise RuntimeError("fixture_execution_failed") from None
    if attempt == 1:
        assert outcome == "captured"
        store.set(marker + ":first-pid", os.getpid(), ex=600)
        os._exit(73)
    assert outcome == "resumed" and self.request.delivery_info.get("redelivered")
    assert int(store.get(marker + ":first-pid")) != os.getpid()
    assert int(store.get(marker + ":scripted-acceptances")) == 1
    assert int(store.get(marker + ":settlements")) == 1
    assert int(store.get(marker + ":persist-callbacks")) == 1
    return {
        "status": "resumed",
        "attempts": 2,
        "redelivered": True,
        "scripted_acceptances": 1,
        "settlement_callbacks": 1,
        "persist_callbacks": 1,
    }
