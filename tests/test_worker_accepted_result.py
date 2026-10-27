"""The early latch stages model facts, not a completed artifact projection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.results.accepted import (
    ACCEPTED_KEY,
    accepted_turn,
    decode_accepted,
    promote_accepted,
    stage_accepted,
)
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    CHECKPOINT_KEY,
    PreparedCheckpointInvalid,
    PreparedTurnCheckpoint,
)


def fixture():
    return dict(
        job_id=str(uuid4()),
        owner_id=str(uuid4()),
        thread_id="synthetic-thread",
        reply="accepted reply",
        model="synthetic",
        usage={
            "total_tokens": 3,
            "per_call_usage": [
                {
                    "call_id": "receipt-1",
                    "provider": "openai",
                    "model": "synthetic",
                    "prompt": 2,
                    "completion": 1,
                }
            ],
        },
    )


@pytest.mark.asyncio
async def test_first_latch_stages_without_commit_or_artifact_metadata():
    values = fixture()
    checkpoint = accepted_turn(**values)
    repo = SimpleNamespace(
        stage_accepted_turn=AsyncMock(return_value=True),
        lock_prepared_turn=AsyncMock(
            return_value={
                "status": ProcessingStatus.PROCESSING,
                "payload": {"thread_id": values["thread_id"]},
            }
        ),
    )
    session = AsyncMock()
    assert await stage_accepted(repo, session, checkpoint)
    session.commit.assert_not_awaited()
    assert checkpoint.payload()["body"]["metadata"] == {}
    assert checkpoint.payload()["body"]["usage"] == values["usage"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["replay", "collision", "terminal", "prepared", "owner", "outage"]
)
async def test_latch_replay_never_replaces_an_owned_accepted_value(fault, caplog):
    values = fixture()
    checkpoint = accepted_turn(**values)
    payload = {"thread_id": values["thread_id"], ACCEPTED_KEY: checkpoint.payload()}
    job = SimpleNamespace(status=ProcessingStatus.PROCESSING, payload=payload)
    repo = SimpleNamespace(
        stage_accepted_turn=AsyncMock(return_value=False),
        fetch_job_by_id=AsyncMock(return_value=job),
        lock_prepared_turn=AsyncMock(
            side_effect=lambda *a, **k: {"status": job.status, "payload": job.payload}
        ),
    )
    if fault == "collision":
        payload[ACCEPTED_KEY] = accepted_turn(**{**values, "reply": "other reply"}).payload()
    elif fault == "terminal":
        job.status = ProcessingStatus.SUCCESS
    elif fault == "prepared":
        payload[CHECKPOINT_KEY] = {}
    elif fault == "owner":
        payload[ACCEPTED_KEY] = accepted_turn(**{**values, "owner_id": str(uuid4())}).payload()
    elif fault == "outage":
        repo.stage_accepted_turn.side_effect = RuntimeError("private-sql-body-marker")
    session = AsyncMock()
    if fault == "replay":
        assert not await stage_accepted(repo, session, checkpoint)
    else:
        with pytest.raises(PreparedCheckpointInvalid, match="Accepted result unavailable") as error:
            await stage_accepted(repo, session, checkpoint)
        assert "private-sql-body-marker" not in str(error.value) + caplog.text
    session.commit.assert_not_awaited()


def test_prepared_artifact_metadata_cannot_be_reinterpreted_as_an_early_latch():
    values = fixture()
    unsafe = PreparedTurnCheckpoint.create(**values, metadata={"generated_files": []})
    with pytest.raises(PreparedCheckpointInvalid):
        decode_accepted(
            unsafe.payload(), **{key: values[key] for key in ("job_id", "owner_id", "thread_id")}
        )


def test_latch_rejects_non_numeric_usage_and_does_not_stringify_objects():
    values = fixture()
    for usage in ({"total_tokens": "private-body"}, {"total_tokens": object()}):
        with pytest.raises(PreparedCheckpointInvalid):
            accepted_turn(**{**values, "usage": usage})


@pytest.mark.parametrize("field", ["model", "provider", "call_id", "receipt_id"])
def test_provenance_slots_do_not_accept_urls_or_response_text(field):
    values = fixture()
    for marker in ("https://private.invalid/marker", "raw response text", object()):
        usage = {"per_call_usage": [{field: marker, "prompt": 1, "completion": 1}]}
        with pytest.raises(PreparedCheckpointInvalid):
            accepted_turn(**{**values, "usage": usage})


def test_missing_provenance_does_not_discard_incurred_usage():
    values = fixture()
    usage = {
        "per_call_usage": [{"model": None, "provider": None, "prompt": 2, "completion": 1}],
        "total_tokens": 3,
    }
    checkpoint = accepted_turn(**{**values, "model": None, "usage": usage})
    assert checkpoint.payload()["body"]["usage"] == usage


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "reply",
        "model",
        "usage",
        "owner",
        "thread",
        "corrupt",
        "terminal",
        "missing",
        "outage",
    ],
)
async def test_promotion_preserves_accepted_facts_under_owned_lock(fault, caplog):
    values = fixture()
    accepted = accepted_turn(**values)
    changed = dict(values)
    if fault == "reply":
        changed["reply"] = "replacement reply"
    elif fault == "model":
        changed["model"] = "another/model"
    elif fault == "usage":
        changed["usage"] = {"total_tokens": 100}
    elif fault == "owner":
        changed["owner_id"] = str(uuid4())
    elif fault == "thread":
        changed["thread_id"] = "other-thread"
    prepared = PreparedTurnCheckpoint.create(
        **changed, metadata={"public": {"execution_status": "completed"}}
    )
    payload = {"thread_id": values["thread_id"], ACCEPTED_KEY: accepted.payload()}
    if fault == "corrupt":
        payload[ACCEPTED_KEY]["sha256"] = "0" * 64
    elif fault == "missing":
        payload.pop(ACCEPTED_KEY)
    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(
            return_value={
                "status": ProcessingStatus.SUCCESS
                if fault == "terminal"
                else ProcessingStatus.PROCESSING,
                "payload": payload,
            }
        ),
        stage_prepared_turn=AsyncMock(return_value=True),
    )
    if fault == "outage":
        repo.lock_prepared_turn.side_effect = RuntimeError("private-promotion-body-marker")
    session = AsyncMock()
    if fault is None:
        assert await promote_accepted(repo, session, prepared)
        repo.stage_prepared_turn.assert_awaited_once()
    else:
        with pytest.raises(PreparedCheckpointInvalid, match="Accepted result unavailable") as error:
            await promote_accepted(repo, session, prepared)
        repo.stage_prepared_turn.assert_not_awaited()
        assert "private-promotion-body-marker" not in str(error.value) + caplog.text
    session.commit.assert_not_awaited()
    assert payload.get(ACCEPTED_KEY) == accepted.payload() or fault in {"corrupt", "missing"}
