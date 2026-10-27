"""Sealed recovery imports receipts once; unavailable/active state never settles."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.infrastructure.agents_client.document_audit.recovery import (
    AuditRecoverySnapshot,
    decode_snapshot,
    recover_document_audit,
)
from service.infrastructure.sidecar import SidecarClient
from service.services.chat.application.documents.audit import recovery as recovery
from service.services.chat.persistence.documents.audit.attempts import RecordedAuditResult


def checkpoint(attempt):
    return {
        "schema_version": 1,
        "attempt_id": str(attempt),
        "revision": 1,
        "receipts": [
            {
                "receipt_id": "fixture-call",
                "model": "GigaChat-2-Max",
                "provider": "gigachat",
                "kind": "document_visual_audit",
                "prompt": 30,
                "completion": 3,
                "estimated": False,
            }
        ],
    }


def snapshot(attempt):
    return {
        "state": "terminal",
        "checkpoint": checkpoint(attempt),
        "result": {
            "status": "passed",
            "passed": True,
            "retryable": False,
        },
    }


@pytest.mark.parametrize(
    "fault", ["attempt", "kind", "bool", "extra", "state", "active_result", "raw_body"]
)
def test_invalid_recovery_snapshot_never_proves_completion(fault):
    attempt = uuid4()
    body = snapshot(attempt)
    if fault == "attempt":
        body["checkpoint"]["attempt_id"] = str(uuid4())
    elif fault == "kind":
        body["checkpoint"]["receipts"][0]["kind"] = "chat"
    elif fault == "bool":
        body["result"]["passed"] = 1
    elif fault == "extra":
        body["capability"] = "PRIVATE_MARKER"
    elif fault == "state":
        body["state"] = ["terminal"]
    elif fault == "active_result":
        body["state"] = "active"
    else:
        body["result"]["body"] = "PRIVATE_MARKER"
    decoded = decode_snapshot(body, attempt_id=attempt)
    assert decoded == AuditRecoverySnapshot("unavailable")


def test_positive_recovery_requires_a_recorded_vision_call():
    attempt = uuid4()
    body = snapshot(attempt)
    body["checkpoint"] = None
    assert decode_snapshot(body, attempt_id=attempt) == AuditRecoverySnapshot("unavailable")
    body["result"] = {"status": "vision_unavailable", "passed": False, "retryable": True}
    assert decode_snapshot(body, attempt_id=attempt).state == "terminal"


@pytest.mark.asyncio
async def test_rpc_is_read_only_and_never_grants_fresh_execution(monkeypatch):
    attempt = uuid4()
    request = AsyncMock(return_value=snapshot(attempt))
    monkeypatch.setattr(SidecarClient, "request_json", request)
    result = await recover_document_audit(
        object(),
        workspace_ref={"user_id": "fixture-owner"},
        build_id="fixture-build",
        attempt_id=attempt,
    )
    assert result.state == "terminal" and result.outcome["passed"]
    payload = request.await_args.kwargs["json_body"]
    assert payload["recovery_only"] is True
    assert "fresh_attempt" not in payload and "provider_policy" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["active", "unknown", "unavailable"])
async def test_unresolved_producer_never_promotes_or_restarts(monkeypatch, state):
    monkeypatch.setattr(recovery, "lock_started", AsyncMock(return_value=True))
    monkeypatch.setattr(
        recovery, "recover_document_audit", AsyncMock(return_value=AuditRecoverySnapshot(state))
    )
    stage = AsyncMock()
    record = AsyncMock()
    monkeypatch.setattr(recovery, "stage_checkpoint", stage)
    monkeypatch.setattr(recovery, "record_merged_result", record)
    assert (
        await recovery.recover_started_result(
            config=object(),
            session=AsyncMock(),
            row={"build_id": "fixture-build"},
            ref={},
            attempt_id=uuid4(),
        )
        is None
    )
    stage.assert_not_awaited()
    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_owned_sealed_recovery_commits_receipt_before_terminal(monkeypatch):
    attempt = uuid4()
    body = snapshot(attempt)
    events = []
    session = SimpleNamespace(commit=AsyncMock(side_effect=lambda: events.append("commit")))
    monkeypatch.setattr(recovery, "lock_started", AsyncMock(return_value=True))
    monkeypatch.setattr(
        recovery,
        "recover_document_audit",
        AsyncMock(return_value=decode_snapshot(body, attempt_id=attempt)),
    )

    async def stage(*args, **kwargs):
        assert kwargs["payload"] == checkpoint(attempt)
        events.append("checkpoint")

    known = {"total": 33}

    async def record(*args, **kwargs):
        assert kwargs["usage"] == {} and kwargs["failure_code"] == "attestation_pending"
        events.append("terminal")
        return RecordedAuditResult(known, "attestation_pending")

    monkeypatch.setattr(recovery, "stage_checkpoint", stage)
    monkeypatch.setattr(recovery, "record_merged_result", record)
    result = await recovery.recover_started_result(
        config=object(),
        session=session,
        row={"build_id": "fixture-build"},
        ref={},
        attempt_id=attempt,
    )
    assert result.usage == known
    assert events == ["commit", "checkpoint", "commit", "terminal", "commit"]


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [[False], [True, False]])
async def test_missing_or_changed_owner_scope_never_records(monkeypatch, owned):
    attempt = uuid4()
    monkeypatch.setattr(recovery, "lock_started", AsyncMock(side_effect=owned))
    read = AsyncMock(return_value=decode_snapshot(snapshot(attempt), attempt_id=attempt))
    record = AsyncMock()
    stage = AsyncMock()
    monkeypatch.setattr(recovery, "recover_document_audit", read)
    monkeypatch.setattr(recovery, "record_merged_result", record)
    monkeypatch.setattr(recovery, "stage_checkpoint", stage)
    result = await recovery.recover_started_result(
        config=object(),
        session=AsyncMock(),
        row={"build_id": "fixture-build"},
        ref={},
        attempt_id=attempt,
    )
    assert result is None
    record.assert_not_awaited()
    stage.assert_not_awaited()
    assert read.await_count == (1 if owned[0] else 0)
