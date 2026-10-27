"""Journal mismatch cannot be bypassed by accepted/prepared redelivery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.billing.execution_accounting import (
    ExecutionAccounting,
)
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import (
    JournalReceipt,
    UsageJournal,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.results import (
    early_resume as early_result_resume,
)
from service.services.chat.infrastructure.chat_worker.results.accepted import (
    ACCEPTED_KEY,
    accepted_turn,
)
from service.services.chat.infrastructure.chat_worker.results.prepared import (
    PreparedResultCoordinator,
)
from service.services.chat.infrastructure.chat_worker.run_contracts import MutableRunState
from service.services.jobs.persistence.transitions import EXECUTION_KEY, USAGE_JOURNAL_KEY
from tests.test_worker_prepared_result_resume import prepared_fixture, repository


def bound_payload(usage):
    attempt = str(uuid4())
    receipt = usage["per_call_usage"][0]
    journal = UsageJournal(
        attempt,
        1,
        (
            JournalReceipt(
                "receipt-1",
                "openai",
                "synthetic",
                None,
                receipt["prompt"],
                receipt["completion"],
                False,
            ),
        ),
    )
    return {EXECUTION_KEY: attempt, USAGE_JOURNAL_KEY: journal.payload()}


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "usage", "attempt", "corrupt"])
async def test_prepared_recovery_validates_owned_journal_before_side_effects(fault):
    request, _, usage, _, envelope = prepared_fixture()
    repo = repository(envelope)
    payload = repo.lock_prepared_turn.return_value["payload"]
    payload.update(bound_payload(usage))
    if fault == "usage":
        payload[USAGE_JOURNAL_KEY]["receipts"][0]["prompt"] += 1
    elif fault == "attempt":
        payload[EXECUTION_KEY] = str(uuid4())
    elif fault == "corrupt":
        payload[USAGE_JOURNAL_KEY] = {"PRIVATE_MARKER": "invalid"}
    session = AsyncMock()
    session.scalar.return_value = 0
    files = SimpleNamespace(fetch_file_metadata=AsyncMock())
    state = MutableRunState()
    call = PreparedResultCoordinator().restore(
        request=request,
        repository=repo,
        session=session,
        state=state,
        file_service=files,
        catalog_recorder=AsyncMock(),
    )
    if fault:
        with pytest.raises(JobStateUnavailable) as error:
            await call
        assert "PRIVATE_MARKER" not in str(error.value)
        assert state.restored_result is None
    else:
        assert await call
        assert state.restored_result["usage"] == usage
    files.fetch_file_metadata.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_early_result_mismatch_precedes_materialization(monkeypatch):
    request, _, usage, _, _ = prepared_fixture()
    payload = bound_payload(usage)
    payload[USAGE_JOURNAL_KEY]["receipts"][0]["completion"] += 1
    payload[ACCEPTED_KEY] = accepted_turn(
        job_id=request.job_id,
        owner_id=request.user_id,
        thread_id=request.thread_id,
        reply="synthetic",
        model="synthetic",
        usage=usage,
    ).payload()
    recover = AsyncMock()
    monkeypatch.setattr(early_result_resume, "recover_materialization", recover)
    with pytest.raises(JobStateUnavailable, match="Usage checkpoint mismatch"):
        await early_result_resume.restore_accepted(
            request=request,
            repository=object(),
            session=AsyncMock(),
            file_service=object(),
            payload=payload,
            catalog_recorder=AsyncMock(),
        )
    recover.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "foreign", "projection"])
async def test_prepared_recovery_requires_owned_reservation_evidence(fault):
    request, private, _, _, envelope = prepared_fixture()
    repo = repository(envelope)
    payload = repo.lock_prepared_turn.return_value["payload"]
    attempt = str(uuid4())
    estimate = private["reserved_estimate"] + (1 if fault == "projection" else 0)
    payload.update(
        {
            "thread_id": request.thread_id,
            EXECUTION_KEY: attempt,
            "_execution_accounting_v1": ExecutionAccounting(
                attempt,
                private["reservation_id"],
                estimate,
            ).payload(),
        }
    )
    row = (
        None
        if fault == "foreign"
        else {
            "tokens_reserved": estimate,
            "status": "refunded",
            "expired": True,
            "charged": False,
        }
    )
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(
        mappings=lambda: SimpleNamespace(first=lambda: row)
    )
    session.scalar.return_value = 0
    state = MutableRunState()
    files = SimpleNamespace(fetch_file_metadata=AsyncMock())
    call = PreparedResultCoordinator().restore(
        request=request,
        repository=repo,
        session=session,
        state=state,
        file_service=files,
        catalog_recorder=AsyncMock(),
    )
    if fault:
        with pytest.raises(JobStateUnavailable):
            await call
        assert state.restored_result is None
    else:
        assert await call
        assert state.reservation_id == private["reservation_id"]
    files.fetch_file_metadata.assert_not_awaited()
    session.commit.assert_not_awaited()
