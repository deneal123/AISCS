"""Private reservation facts cannot be lost through stale whole-payload writes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.billing.execution_accounting import (
    ExecutionAccounting,
    stage_execution_accounting,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)
from service.services.jobs.persistence.transitions import guarded_payload
from service.shared.repositories.exceptions import RepositoryError


def test_stale_update_preserves_execution_accounting():
    accounting = {
        "schema_version": 1,
        "attempt_id": str(uuid4()),
        "reservation_id": str(uuid4()),
        "reserved_estimate": 70,
    }
    stored = {"thread_id": "synthetic", "_execution_accounting_v1": accounting}
    result = guarded_payload(
        ProcessingStatus.PROCESSING,
        stored,
        ProcessingStatus.PROCESSING,
        {"thread_id": "synthetic"},
        None,
    )
    assert result["_execution_accounting_v1"] == accounting


def fixture():
    state = MutableRunState(
        execution_attempt_id=str(uuid4()),
        reservation_id=str(uuid4()),
        reserved_estimate=70,
    )
    request = WorkerRunRequest(str(uuid4()), str(uuid4()), "PRIVATE_REQUEST", str(uuid4()))
    row = {
        "status": ProcessingStatus.PROCESSING,
        "payload": {
            "thread_id": request.thread_id,
            "_execution_attempt_v1": state.execution_attempt_id,
        },
    }
    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(return_value=row),
        stage_execution_accounting=AsyncMock(return_value=True),
    )
    return state, request, row, repo


@pytest.mark.parametrize(
    "fault", ["extra", "boolean", "negative", "huge", "uuid", "version", "no_hold"]
)
def test_closed_codec_rejects_untrusted_accounting(fault):
    state, _, _, _ = fixture()
    payload = ExecutionAccounting(state.execution_attempt_id, state.reservation_id, 70).payload()
    if fault == "extra":
        payload["capability"] = "PRIVATE_MARKER"
    elif fault == "boolean":
        payload["reserved_estimate"] = True
    elif fault == "negative":
        payload["reserved_estimate"] = -1
    elif fault == "huge":
        payload["reserved_estimate"] = 1_000_000_001
    elif fault == "uuid":
        payload["attempt_id"] = "PRIVATE_MARKER"
    elif fault == "version":
        payload["schema_version"] = True
    else:
        payload["reservation_id"] = None
    with pytest.raises(JobStateUnavailable) as error:
        ExecutionAccounting.decode(payload)
    assert str(error.value) == "Execution accounting unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", [None, "missing", "terminal", "thread", "attempt", "conflict", "outage"]
)
async def test_owned_bound_context_is_staged_without_commit(fault):
    state, request, row, repo = fixture()
    if fault == "missing":
        repo.lock_prepared_turn.return_value = None
    elif fault == "terminal":
        row["status"] = ProcessingStatus.SUCCESS
    elif fault == "thread":
        row["payload"]["thread_id"] = str(uuid4())
    elif fault == "attempt":
        row["payload"]["_execution_attempt_v1"] = str(uuid4())
    elif fault == "conflict":
        row["payload"]["_execution_accounting_v1"] = {}
    elif fault == "outage":
        repo.stage_execution_accounting.side_effect = RuntimeError("PRIVATE_MARKER")
    session = AsyncMock()
    if fault:
        with pytest.raises(JobStateUnavailable) as error:
            await stage_execution_accounting(repo, session, request, state)
        assert "PRIVATE_MARKER" not in str(error.value)
    else:
        await stage_execution_accounting(repo, session, request, state)
        saved = repo.stage_execution_accounting.await_args.args[4]
        assert "PRIVATE_REQUEST" not in saved
        row["payload"]["_execution_accounting_v1"] = ExecutionAccounting(
            state.execution_attempt_id,
            state.reservation_id,
            state.reserved_estimate,
        ).payload()
        await stage_execution_accounting(repo, session, request, state)
        repo.stage_execution_accounting.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("mode", ["insert", "replace"])
def test_generic_transition_cannot_author_accounting(mode):
    accounting = ExecutionAccounting(str(uuid4()), None, 0).payload()
    stored = {} if mode == "insert" else {"_execution_accounting_v1": accounting}
    incoming = {"_execution_accounting_v1": {**accounting, "reserved_estimate": 20}}
    with pytest.raises(RepositoryError):
        guarded_payload(
            ProcessingStatus.PROCESSING, stored, ProcessingStatus.PROCESSING, incoming, None
        )
