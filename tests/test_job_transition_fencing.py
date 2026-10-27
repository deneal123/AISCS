"""Stale status writers cannot erase accepted facts or reopen terminal jobs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus, ServiceType
from service.services.jobs.persistence.job_repository import JobRepository
from service.services.jobs.persistence.transitions import guarded_payload
from service.shared.repositories.exceptions import RepositoryError


def session_with(status, payload):
    result = Mock()
    result.one.return_value = (status, payload)
    return SimpleNamespace(
        execute=AsyncMock(return_value=result), merge=AsyncMock(), flush=AsyncMock()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key", ["_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1"]
)
async def test_stale_ongoing_update_preserves_recovery_facts(key):
    session = session_with(ProcessingStatus.PROCESSING, {key: {"private": "marker"}})
    job = JobLogic(
        user_id=uuid4(),
        type=ServiceType.CHAT,
        status=ProcessingStatus.PROCESSING,
        payload={"thread_id": "thread"},
    )
    result = await JobRepository(object()).update_job_status(job, session=session)
    assert result.payload[key] == {"private": "marker"}


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [ProcessingStatus.SUCCESS, ProcessingStatus.FAILURE])
async def test_stale_update_cannot_reopen_terminal_state(terminal):
    session = session_with(terminal, {"reply": "canonical"})
    job = JobLogic(
        user_id=uuid4(),
        type=ServiceType.CHAT,
        status=ProcessingStatus.PROCESSING,
        payload={"reply": "stale"},
    )
    with pytest.raises(RepositoryError):
        await JobRepository(object()).update_job_status(job, session=session)
    session.merge.assert_not_awaited()


@pytest.mark.parametrize(
    "key", ["_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1"]
)
def test_successful_cleanup_requires_exact_observed_facts(key):
    facts = {key: {"private": "accepted"}}
    with pytest.raises(RepositoryError):
        guarded_payload(
            ProcessingStatus.PROCESSING, facts, ProcessingStatus.SUCCESS, {"reply": "done"}, None
        )
    with pytest.raises(RepositoryError):
        guarded_payload(
            ProcessingStatus.PROCESSING,
            facts,
            ProcessingStatus.SUCCESS,
            {"reply": "done"},
            {key: {"private": "stale"}},
        )
    assert guarded_payload(
        ProcessingStatus.PROCESSING,
        facts,
        ProcessingStatus.SUCCESS,
        {"reply": "done", **facts},
        facts,
    ) == {"reply": "done"}


@pytest.mark.parametrize(
    "key", ["_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1"]
)
def test_failure_cannot_discard_accepted_usage(key):
    facts = {key: {"private": "accepted"}}
    with pytest.raises(RepositoryError):
        guarded_payload(ProcessingStatus.PROCESSING, facts, ProcessingStatus.FAILURE, {}, facts)


def test_unknown_recovery_facts_cannot_be_injected_by_generic_status_writer():
    with pytest.raises(RepositoryError):
        guarded_payload(
            ProcessingStatus.PROCESSING,
            {},
            ProcessingStatus.PROCESSING,
            {"_accepted_turn_v1": {}},
            None,
        )


def test_terminal_payload_cannot_be_replaced_even_with_same_status():
    with pytest.raises(RepositoryError):
        guarded_payload(
            ProcessingStatus.SUCCESS,
            {"reply": "canonical"},
            ProcessingStatus.SUCCESS,
            {"reply": "stale"},
            {},
        )


def test_generic_status_writer_preserves_harness_retry_counter_but_cannot_replace_it():
    marker = {"attempt_id": str(uuid4()), "count": 3, "state": "blocked"}
    key = "_harness_transport_retry_v1"
    stored = {key: marker, "thread_id": str(uuid4())}
    result = guarded_payload(
        ProcessingStatus.PROCESSING, stored, ProcessingStatus.PROCESSING, {}, None
    )
    assert result[key] == marker
    with pytest.raises(RepositoryError):
        guarded_payload(
            ProcessingStatus.PROCESSING,
            stored,
            ProcessingStatus.PROCESSING,
            {key: {**marker, "count": 1, "state": "pending"}},
            None,
        )


@pytest.mark.parametrize("status", [ProcessingStatus.PROCESSING, ProcessingStatus.SUCCESS])
def test_document_scope_survives_stale_job_payload_and_cannot_be_replaced(status):
    key = "_harness_document_scope_v1"
    scope = {"schema_version": 1, "selection": {"path": "documents/cats", "block_ids": ["intro"]}}
    stored = {key: scope, "thread_id": str(uuid4())}
    projected = guarded_payload(ProcessingStatus.PROCESSING, stored, status, {}, None)
    assert projected[key] == scope
    with pytest.raises(RepositoryError):
        guarded_payload(
            ProcessingStatus.PROCESSING,
            stored,
            ProcessingStatus.PROCESSING,
            {key: {"schema_version": 1, "selection": {"path": "documents/other"}}},
            None,
        )
