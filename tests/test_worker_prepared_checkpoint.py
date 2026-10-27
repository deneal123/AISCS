"""Privacy, immutability and atomic admission of the private result envelope."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    CHECKPOINT_KEY,
    MAX_CHECKPOINT_BYTES,
    PreparedCheckpointInvalid,
    PreparedTurnCheckpoint,
    store_prepared_turn,
)


def input_values():
    return {
        "job_id": str(uuid4()),
        "owner_id": str(uuid4()),
        "thread_id": "synthetic-thread",
        "reply": "private-result-content-marker",
        "model": "synthetic/model",
        "metadata": {"execution_status": "completed", "context": {"fraction": 0.25}},
        "usage": {
            "total": 33,
            "calls": [{"model": "synthetic/model", "prompt": 30, "completion": 3}],
        },
    }


def bindings(values):
    return {key: values[key] for key in ("job_id", "owner_id", "thread_id")}


def test_checkpoint_is_immutable_and_does_not_reflect_content_in_repr():
    values = input_values()
    checkpoint = PreparedTurnCheckpoint.create(**values)
    accepted = copy.deepcopy(checkpoint.payload())
    values["metadata"]["context"]["fraction"] = 1.0
    projected = checkpoint.payload()
    projected["body"]["reply"] = "changed"
    assert checkpoint.payload() == accepted
    assert "private-result-content-marker" not in repr(checkpoint)
    assert PreparedTurnCheckpoint.decode(accepted, **bindings(values)).digest == checkpoint.digest


@pytest.mark.parametrize("key", ["job_id", "owner_id", "thread_id"])
def test_checkpoint_cannot_move_to_another_owner_job_or_thread(key):
    values = input_values()
    checkpoint = PreparedTurnCheckpoint.create(**values)
    bound = bindings(values)
    bound[key] = str(uuid4())
    with pytest.raises(PreparedCheckpointInvalid):
        PreparedTurnCheckpoint.decode(checkpoint.payload(), **bound)


@pytest.mark.parametrize("mutation", ["digest", "reply", "unknown", "version", "boolean_version"])
def test_corrupt_or_future_checkpoint_is_not_a_recoverable_result(mutation):
    values = input_values()
    envelope = PreparedTurnCheckpoint.create(**values).payload()
    if mutation == "digest":
        envelope["sha256"] = "0" * 64
    elif mutation == "reply":
        envelope["body"]["reply"] = "changed"
    elif mutation == "unknown":
        envelope["body"]["unknown"] = "private-body-marker"
    else:
        envelope["body"]["version"] = True if mutation == "boolean_version" else 2
    with pytest.raises(PreparedCheckpointInvalid) as caught:
        PreparedTurnCheckpoint.decode(envelope, **bindings(values))
    assert "private-body-marker" not in str(caught.value)


@pytest.mark.parametrize(
    "key",
    [
        "coordination_capability",
        "CoordinationCapability",
        "workspace-token",
        "headers",
        "engine_env",
        "b64_json",
        "_pending_artifacts",
        "file_key",
        "presigned_url",
        "file_url",
        "functions_state_id",
        "original_error",
    ],
)
def test_private_context_and_inline_artifacts_cannot_enter_checkpoint(key):
    values = input_values()
    values["metadata"]["nested"] = [{key: "private-credential-marker"}]
    with pytest.raises(PreparedCheckpointInvalid) as caught:
        PreparedTurnCheckpoint.create(**values)
    assert "private-credential-marker" not in str(caught.value)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), object()])
def test_checkpoint_rejects_non_json_or_non_finite_values(invalid):
    values = input_values()
    values["usage"]["unknown"] = invalid
    with pytest.raises(PreparedCheckpointInvalid):
        PreparedTurnCheckpoint.create(**values)


def test_checkpoint_has_a_hard_encoded_size_limit():
    values = input_values()
    values["reply"] = "я" * MAX_CHECKPOINT_BYTES
    with pytest.raises(PreparedCheckpointInvalid):
        PreparedTurnCheckpoint.create(**values)


@pytest.mark.asyncio
async def test_fresh_checkpoint_uses_atomic_repository_admission_without_committing():
    values = input_values()
    checkpoint = PreparedTurnCheckpoint.create(**values)
    session = AsyncMock()
    repository = SimpleNamespace(
        stage_prepared_turn=AsyncMock(return_value=True),
        fetch_job_by_id=AsyncMock(),
        lock_prepared_turn=AsyncMock(
            return_value={
                "status": ProcessingStatus.PROCESSING,
                "payload": {"thread_id": values["thread_id"]},
            }
        ),
    )
    assert await store_prepared_turn(repository, session, checkpoint)
    repository.stage_prepared_turn.assert_awaited_once()
    assert json.loads(repository.stage_prepared_turn.await_args.args[3]) == checkpoint.payload()
    repository.fetch_job_by_id.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["same", "collision", "terminal", "missing", "unavailable"])
async def test_replay_does_not_overwrite_a_different_or_terminal_result(state):
    values = input_values()
    checkpoint = PreparedTurnCheckpoint.create(**values)
    previous = checkpoint
    if state == "collision":
        previous = PreparedTurnCheckpoint.create(**{**values, "reply": "different"})
    job = SimpleNamespace(
        status=ProcessingStatus.SUCCESS if state == "terminal" else ProcessingStatus.PROCESSING,
        payload={"thread_id": values["thread_id"], CHECKPOINT_KEY: previous.payload()},
    )
    repository = SimpleNamespace(
        stage_prepared_turn=AsyncMock(return_value=False),
        fetch_job_by_id=AsyncMock(return_value=None if state == "missing" else job),
        lock_prepared_turn=AsyncMock(
            return_value=None
            if state == "missing"
            else {
                "status": job.status,
                "payload": job.payload,
            }
        ),
    )
    if state == "unavailable":
        repository.stage_prepared_turn.side_effect = RuntimeError("private-db-body-marker")
    session = AsyncMock()
    if state == "same":
        assert not await store_prepared_turn(repository, session, checkpoint)
    else:
        with pytest.raises(PreparedCheckpointInvalid) as caught:
            await store_prepared_turn(repository, session, checkpoint)
        assert "private-db-body-marker" not in str(caught.value)
    session.commit.assert_not_awaited()
