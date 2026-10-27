"""Checkpoint ownership, refinement and freeze precede any transport integration."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from service.services.chat.persistence.documents.audit import attempts as attempts
from service.services.chat.persistence.documents.audit import checkpoint as checkpoint


def _payload():
    return {
        "schema_version": 1,
        "attempt_id": str(uuid4()),
        "revision": 1,
        "receipts": [
            {
                "receipt_id": "accepted-call",
                "provider": "gigachat",
                "model": "GigaChat-2-Max",
                "kind": "document_visual_audit",
                "prompt": 30,
                "completion": 3,
                "estimated": False,
            }
        ],
    }


def _row():
    return {
        "id": uuid4(),
        "user_id": uuid4(),
        "build_id": "fixture-build",
        "source_digest": "a" * 64,
        "artifact_sha256": "b" * 64,
    }


def _session(current):
    selected = SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: current))
    return SimpleNamespace(
        execute=AsyncMock(side_effect=[selected, SimpleNamespace(rowcount=1)]), commit=AsyncMock()
    )


@pytest.mark.asyncio
async def test_stage_is_scoped_and_never_commits_or_finalizes():
    row = _row()
    session = _session({"state": "started", "usage_envelope": None})
    assert await checkpoint.stage_checkpoint(session, row=row, payload=_payload())
    sql, params = session.execute.call_args.args
    assert all(key in params for key in ("publication", "owner", "build", "source", "artifact"))
    assert params["owner"] == row["user_id"]
    assert "state='started'" in str(sql)
    assert "charge_pending" not in str(sql)
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [None, "charge_pending", "settled"])
async def test_missing_or_sealed_attempt_is_not_mutated(state):
    session = _session(None if state is None else {"state": state, "usage_envelope": {}})
    with pytest.raises(checkpoint.AuditCheckpointUnavailable):
        await checkpoint.stage_checkpoint(session, row=_row(), payload=_payload())
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_exact_replay_is_acknowledged_without_an_update():
    payload = _payload()
    session = _session({"state": "started", "usage_envelope": {checkpoint.JOURNAL_KEY: payload}})
    assert not await checkpoint.stage_checkpoint(session, row=_row(), payload=payload)
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_wrong_kind_is_rejected_before_lookup():
    payload = _payload()
    payload["receipts"][0]["kind"] = "chat"
    session = _session(None)
    with pytest.raises(checkpoint.AuditCheckpointUnavailable):
        await checkpoint.stage_checkpoint(session, row=_row(), payload=payload)
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_estimate_refinement_and_new_call_preserve_distinct_expense():
    previous = _payload()
    previous["receipts"][0]["estimated"] = True
    incoming = copy.deepcopy(previous)
    incoming["revision"] = 2
    incoming["receipts"][0].update(prompt=20, completion=2, estimated=False)
    second = copy.deepcopy(incoming["receipts"][0])
    second.update(receipt_id="second-call", model="GigaChat-2", prompt=10, completion=1)
    incoming["receipts"].append(second)
    session = _session({"state": "started", "usage_envelope": {checkpoint.JOURNAL_KEY: previous}})

    assert await checkpoint.stage_checkpoint(session, row=_row(), payload=incoming)
    saved = json.loads(session.execute.call_args.args[1]["usage"])
    assert saved[checkpoint.JOURNAL_KEY] == incoming
    assert saved["total"] == 33
    assert len(saved["calls"]) == 2
    assert "model" not in saved
    assert saved["calls"][0]["receipt_id"] == "accepted-call"
    assert not saved["calls"][0].get("estimated", False)
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["revision", "provenance", "counters", "erase", "attempt"])
async def test_nonmonotonic_update_never_overwrites_checkpoint(mutation):
    previous = _payload()
    incoming = copy.deepcopy(previous)
    incoming["revision"] = 2
    if mutation == "revision":
        incoming["revision"] = 1
        incoming["receipts"][0]["completion"] = 4
    elif mutation == "provenance":
        incoming["receipts"][0]["model"] = "GigaChat-2"
    elif mutation == "counters":
        incoming["receipts"][0]["completion"] = 4
    elif mutation == "erase":
        incoming["receipts"] = []
    else:
        incoming["attempt_id"] = str(uuid4())
    session = _session({"state": "started", "usage_envelope": {checkpoint.JOURNAL_KEY: previous}})

    with pytest.raises(checkpoint.AuditCheckpointUnavailable):
        await checkpoint.stage_checkpoint(session, row=_row(), payload=incoming)
    assert session.execute.await_count <= 1
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [[], "", 0, False, {"total": 33}, {checkpoint.JOURNAL_KEY: {}}])
async def test_legacy_or_corrupt_envelope_cannot_be_replaced(stored):
    session = _session({"state": "started", "usage_envelope": stored})
    with pytest.raises(checkpoint.AuditCheckpointUnavailable):
        await checkpoint.stage_checkpoint(session, row=_row(), payload=_payload())
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_database_failure_exposes_only_bounded_error():
    session = _session(None)
    session.execute.side_effect = RuntimeError("private-database-marker")
    with pytest.raises(checkpoint.AuditCheckpointUnavailable) as raised:
        await checkpoint.stage_checkpoint(session, row=_row(), payload=_payload())
    assert str(raised.value) == "document_audit_checkpoint_unavailable"
    assert raised.value.__suppress_context__
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["empty", "refined", "conflicting"])
async def test_terminal_result_preserves_checkpoint_and_returns_persisted_usage(outcome):
    payload = _payload()
    payload["receipts"][0]["estimated"] = True
    incoming = {}
    if outcome != "empty":
        call = copy.deepcopy(payload["receipts"][0])
        call.update(estimated=False, prompt=20, completion=2)
        if outcome == "conflicting":
            call["model"] = "GigaChat-2"
        incoming = {"calls": [call]}
    session = _session({"state": "started", "usage_envelope": {checkpoint.JOURNAL_KEY: payload}})
    recorded = await attempts.record_merged_result(
        session,
        attempt_id=UUID(payload["attempt_id"]),
        usage=incoming,
        failure_code="attestation_pending",
    )
    assert recorded is not None
    persisted = json.loads(session.execute.call_args.args[1]["usage"])
    assert recorded.usage == persisted
    assert persisted[checkpoint.JOURNAL_KEY] == payload
    assert persisted["total"] == (22 if outcome == "refined" else 33)
    assert len(persisted["calls"]) == 1
    assert recorded.failure_code == (
        "provider_protocol" if outcome == "conflicting" else "attestation_pending"
    )
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [None, "charge_pending", "settled"])
async def test_terminal_replay_does_not_change_frozen_expense(state):
    session = _session(None if state is None else {"state": state, "usage_envelope": {}})
    assert await attempts.record_merged_result(session, attempt_id=uuid4(), usage={}) is None
    assert session.execute.await_count == 1


def test_terminal_rejects_checkpoint_of_different_attempt():
    with pytest.raises(checkpoint.AuditCheckpointUnavailable):
        checkpoint.merge_terminal_usage(
            {checkpoint.JOURNAL_KEY: _payload()}, {}, attempt_id=uuid4()
        )


@pytest.mark.parametrize("stored", [{"total": 33}, {"calls": None}, [], False])
def test_terminal_never_erases_undecodable_legacy_expense(stored):
    with pytest.raises(checkpoint.AuditCheckpointUnavailable):
        checkpoint.merge_terminal_usage(stored, {}, attempt_id=uuid4())


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["insert", "existing", "race"])
async def test_only_insert_winner_is_allowed_to_invoke_paid_audit(path):
    identity = uuid4()
    current = {"id": identity, "state": "started", "usage_envelope": {}}

    def selected(value):
        return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: value))

    values = {
        "insert": [None, current],
        "existing": [current],
        "race": [None, None, current],
    }[path]
    session = SimpleNamespace(execute=AsyncMock(side_effect=[selected(value) for value in values]))
    claim = await attempts.begin(session, _row())
    assert claim["id"] == identity
    assert claim["may_execute"] is (path == "insert")
    assert session.execute.await_count == len(values)
