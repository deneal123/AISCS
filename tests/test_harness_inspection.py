"""Read-only, owner-fenced journal inspection contract; no live database."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from service.services.chat.application import harness_capability
from service.services.chat.application.harness_capability import HarnessSettings
from service.services.chat.persistence.harness import effects as harness_effects
from service.services.chat.persistence.harness import grants as harness_grants
from service.services.chat.persistence.harness import runtime as harness_runtime
from service.services.chat.persistence.harness.inspection import inspect_operation
from service.shared.harness_protocol import Exchange, HarnessFailure, OperationStatus, Snapshot
from service.shared.task_contract import digest_payload
from tests.test_harness_runtime_contract import admission


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["paid", "effect"])
async def test_inspection_returns_existing_digest_not_arguments_and_never_dispatches(
    monkeypatch, kind
):
    operation_id = str(uuid4())
    paid = kind == "paid"
    record = {
        "state" if paid else "status": "dispatched",
        "request_digest" if paid else "intent_digest": "a" * 64,
        "request" if paid else "intent": {"private": "PRIVATE_ARGUMENTS"},
        "receipt": None,
    }
    query = AsyncMock(return_value=record)
    monkeypatch.setattr(
        harness_grants if paid else harness_effects, "_read" if paid else "read", query
    )
    db = SimpleNamespace(execute=AsyncMock())
    row = {"task_id": uuid4()}
    result = await inspect_operation(db, row, operation_id, kind)
    query.assert_awaited_once_with(db, row, operation_id)
    assert result.request_digest == "a" * 64 and result.status == "dispatched"
    assert "PRIVATE_ARGUMENTS" not in result.model_dump_json()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_absent_operation_does_not_create_one(monkeypatch):
    monkeypatch.setattr(harness_grants, "_read", AsyncMock(return_value=None))
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HarnessFailure, match="operation_conflict"):
        await inspect_operation(db, {"task_id": uuid4()}, str(uuid4()), "paid")
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("wire_hash", [False, True])
async def test_admission_metadata_does_not_break_known_intent_ack(monkeypatch, wire_hash):
    raw = {"kind": "meta_usage", "operation_id": str(uuid4())}
    saved = {**raw, "_admission_job_v1": str(uuid4())}
    digest = digest_payload(raw if wire_hash else saved)
    monkeypatch.setattr(
        harness_grants,
        "_read",
        AsyncMock(
            return_value={
                "state": "allocated",
                "request_digest": digest,
                "request": saved,
                "receipt": None,
            }
        ),
    )
    result = await inspect_operation(None, {}, raw["operation_id"], "paid")
    assert result.request_digest == digest_payload(raw)
    assert "_admission_job_v1" not in result.model_dump_json()


@pytest.mark.parametrize(
    "change",
    [
        {"operation_kind": "paid", "status": "prepared"},
        {"operation_kind": "effect", "status": "waived"},
        {"status": "succeeded"},
        {"status": "dispatched", "receipt": {"operation_id": str(uuid4()), "status": "unknown"}},
    ],
)
def test_inspection_cannot_claim_a_missing_receipt_or_wrong_operation(change):
    raw = dict(
        operation_id=str(uuid4()), operation_kind="paid", status="unknown", request_digest="a" * 64
    )
    raw.update(change)
    with pytest.raises(ValidationError):
        OperationStatus.model_validate(raw)


@pytest.mark.asyncio
async def test_inspection_available_after_disable_but_still_requires_owned_attempt(monkeypatch):
    task, operation = uuid4(), str(uuid4())
    row = {"task_id": task, "revision": 0}
    owned = AsyncMock(return_value=row)
    monkeypatch.setattr(harness_runtime, "owned_row", owned)
    monkeypatch.setattr(
        harness_runtime, "snapshot", AsyncMock(return_value=Snapshot(admission=admission()))
    )
    monkeypatch.setattr(harness_capability, "settings", lambda: HarnessSettings())
    monkeypatch.setattr(
        harness_effects,
        "read",
        AsyncMock(
            return_value={
                "status": "dispatched",
                "intent_digest": "a" * 64,
                "receipt": None,
            }
        ),
    )
    repo = harness_runtime.HarnessRuntimeRepository(None)
    db = SimpleNamespace()

    async def transaction(body):
        return await body(db)

    monkeypatch.setattr(repo, "_transaction", transaction)
    owner = object()
    request = Exchange(opcode="operation_status", operation_id=operation, operation_kind="effect")
    result = await repo.exchange(owner, request)
    owned.assert_awaited_once_with(db, owner)
    assert result["operation_status"]["status"] == "dispatched"
    owned.side_effect = HarnessFailure("harness_fenced")
    with pytest.raises(HarnessFailure, match="harness_fenced"):
        await repo.exchange(owner, request)


@pytest.mark.parametrize(
    "value",
    [
        {"opcode": "operation_status", "operation_id": str(uuid4())},
        {"opcode": "operation_status", "operation_id": str(uuid4()), "operation_kind": "command"},
        {"opcode": "result", "operation_kind": "effect"},
    ],
)
def test_inspection_request_is_closed(value):
    with pytest.raises(ValidationError):
        Exchange.model_validate(value)
