"""Private receipt journal is bounded, owned, monotonic and never a billing envelope."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import (
    UsageJournal,
    stage_usage_journal,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.jobs.persistence.transitions import (
    EXECUTION_KEY,
    USAGE_JOURNAL_KEY,
    guarded_payload,
)
from service.shared.repositories.exceptions import RepositoryError


def payload():
    return {
        "schema_version": 1,
        "attempt_id": str(uuid4()),
        "revision": 1,
        "receipts": [
            {
                "receipt_id": "call",
                "provider": "openai",
                "model": "synthetic",
                "kind": None,
                "prompt": 20,
                "completion": 2,
                "estimated": True,
            }
        ],
    }


@pytest.mark.parametrize("field", ["model", "receipt_id"])
@pytest.mark.parametrize(
    "value",
    [
        "/PRIVATE_MARKER/key",
        "C:/PRIVATE_MARKER/key",
        "../PRIVATE_MARKER",
        "model/../PRIVATE_MARKER",
    ],
)
def test_path_like_identity_never_enters_a_canonical_journal(field, value):
    data = payload()
    data["receipts"][0][field] = value
    with pytest.raises(JobStateUnavailable) as caught:
        UsageJournal.decode(data)
    assert "PRIVATE_MARKER" not in str(caught.value)


@pytest.mark.parametrize("model", ["openai/gpt-4o", "vendor/model:version", "GigaChat-2-Max"])
def test_qualified_model_identifiers_remain_accepted(model):
    data = payload()
    data["receipts"][0]["model"] = model
    assert UsageJournal.decode(data).receipts[0].model == model


def test_journal_refines_estimate_but_cannot_erase_or_change_identity():
    first = payload()
    second = deepcopy(first)
    second["revision"] = 2
    second["receipts"][0].update(prompt=19, completion=3, estimated=False)
    assert UsageJournal.decode(second).extends(UsageJournal.decode(first))
    for change in ("model", "provider", "receipt_id"):
        changed = deepcopy(second)
        changed["receipts"][0][change] = "mws" if change == "provider" else "other"
        assert not UsageJournal.decode(changed).extends(UsageJournal.decode(first))
    erased = deepcopy(second)
    erased["receipts"][0]["prompt"] = 0
    erased["receipts"][0]["completion"] = 0
    assert not UsageJournal.decode(erased).extends(UsageJournal.decode(first))
    assert not UsageJournal.decode(first).extends(UsageJournal.decode(second))


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt", True),
        ("prompt", -1),
        ("completion", 1_000_000_001),
        ("model", "https://PRIVATE_BODY"),
        ("kind", "PRIVATE_BODY"),
        ("provider", "PRIVATE_BODY"),
        ("estimated", "PRIVATE_BODY"),
    ],
)
def test_invalid_receipt_returns_only_bounded_error(field, value):
    data = payload()
    data["receipts"][0][field] = value
    with pytest.raises(JobStateUnavailable) as error:
        UsageJournal.decode(data)
    assert "PRIVATE_BODY" not in str(error.value)


def test_private_fields_and_duplicate_call_ids_are_rejected():
    data = payload()
    data["receipts"][0]["arguments"] = "PRIVATE_BODY"
    with pytest.raises(JobStateUnavailable):
        UsageJournal.decode(data)
    data = payload()
    data["receipts"] *= 2
    with pytest.raises(JobStateUnavailable):
        UsageJournal.decode(data)


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", ["owner", "thread", "attempt", "terminal"])
async def test_journal_cannot_write_foreign_binding(foreign):
    data = payload()
    stored = {"thread_id": "thread", EXECUTION_KEY: data["attempt_id"]}
    row = {"status": ProcessingStatus.PROCESSING, "payload": stored}
    if foreign == "owner":
        row = None
    elif foreign == "terminal":
        row["status"] = ProcessingStatus.SUCCESS
    else:
        stored["thread_id" if foreign == "thread" else EXECUTION_KEY] = "foreign"
    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(return_value=row),
        stage_usage_journal=AsyncMock(return_value=True),
    )
    with pytest.raises(JobStateUnavailable):
        await stage_usage_journal(
            repo, AsyncMock(), job_id=uuid4(), owner_id=uuid4(), thread_id="thread", payload=data
        )
    repo.stage_usage_journal.assert_not_awaited()


@pytest.mark.asyncio
async def test_identical_replay_does_not_write_or_commit():
    data = payload()
    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(
            return_value={
                "status": ProcessingStatus.PROCESSING,
                "payload": {
                    "thread_id": "thread",
                    EXECUTION_KEY: data["attempt_id"],
                    USAGE_JOURNAL_KEY: data,
                },
            }
        ),
        stage_usage_journal=AsyncMock(return_value=True),
    )
    session = AsyncMock()
    assert not await stage_usage_journal(
        repo, session, job_id=uuid4(), owner_id=uuid4(), thread_id="thread", payload=data
    )
    repo.stage_usage_journal.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_whole_payload_update_preserves_journal_and_rejects_replacement():
    data = payload()
    stored = {USAGE_JOURNAL_KEY: data}
    result = guarded_payload(
        ProcessingStatus.PROCESSING, stored, ProcessingStatus.PROCESSING, {}, None
    )
    assert result[USAGE_JOURNAL_KEY] == data
    changed = deepcopy(data)
    changed["revision"] = 2
    with pytest.raises(RepositoryError):
        guarded_payload(
            ProcessingStatus.PROCESSING,
            stored,
            ProcessingStatus.PROCESSING,
            {USAGE_JOURNAL_KEY: changed},
            None,
        )
