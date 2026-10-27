"""A subsequent metered round/attestation waits for accepted expense persistence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.domain.documents import visual_audit as audit
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.usage.ledger import UsageLedger
from service.infrastructure.document_audit.registry import AuditRegistryUnavailable
from service.presentation.routers.capabilities.audit_checkpoint_barrier import (
    AuditCheckpointBarrier,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", [None, "before_first", "after_first"])
async def test_batch_gate_saves_usage_before_next_call_or_attestation(monkeypatch, fail_at):
    events = []
    registry = SimpleNamespace(attempt=str(uuid4()))

    async def active():
        if fail_at == "before_first":
            raise AuditRegistryUnavailable()

    async def save(payload):
        events.append(("save", len(payload["receipts"])))
        if fail_at == "after_first":
            raise AuditRegistryUnavailable()

    registry.require_active = active
    registry.checkpoint = save
    barrier = AuditCheckpointBarrier(registry)
    monkeypatch.setattr(
        audit,
        "call",
        AsyncMock(
            return_value={
                "audit": {
                    "page_count": 5,
                    "source_digest": "a" * 64,
                    "artifact_sha256": "b" * 64,
                }
            }
        ),
    )
    monkeypatch.setattr(audit, "list_qualified_models", AsyncMock(return_value=["vision-model"]))
    monkeypatch.setattr(audit, "pick_text_model", lambda _: "vision-model")
    monkeypatch.setattr(audit, "download_binary", AsyncMock(return_value=(b"fixture", {})))
    monkeypatch.setattr(audit, "_messages", lambda _: [])
    monkeypatch.setattr(audit, "_audit_tool_arguments", lambda _: {"passed": True, "issues": []})

    async def invoke(*args, execution, **kwargs):
        count = sum(event[0] == "call" for event in events) + 1
        events.append(("call", count))
        execution.usage.record_usage(
            {"prompt": 30, "completion": 3},
            provider="gigachat",
            model="GigaChat-2-Max",
            kind="document_visual_audit",
            receipt_id=f"call-{count}",
        )
        return SimpleNamespace(response=None)

    async def report(*args, passed, **kwargs):
        events.append(("attest", passed))
        return {"state": "ready" if passed else "visual_pending"}

    monkeypatch.setattr(audit, "invoke_model_call", invoke)
    monkeypatch.setattr(audit, "_report", report)
    with use_run_execution(PrivateRunResources()) as execution:
        try:
            result = await audit.audit_document_build(
                {}, "fixture-build", execution=execution, usage_checkpoint=barrier.flush
            )
        finally:
            barrier.close()
        count = {None: 2, "before_first": 0, "after_first": 1}[fail_at]
        assert len(execution.usage.receipts) == count
        assert not execution.usage._observers
    if fail_at is None:
        assert result.passed
        assert events == [
            ("call", 1),
            ("save", 1),
            ("save", 1),
            ("call", 2),
            ("save", 2),
            ("attest", True),
        ]
    else:
        assert result.status == "unavailable" and not result.passed and result.retryable
        assert ("attest", True) not in events
        assert sum(event[0] == "call" for event in events) == count


@pytest.mark.asyncio
async def test_barrier_rejects_second_ledger_without_mixing_runs():
    registry = SimpleNamespace(
        attempt=str(uuid4()), require_active=AsyncMock(), checkpoint=AsyncMock()
    )
    barrier = AuditCheckpointBarrier(registry)
    first = UsageLedger()
    try:
        await barrier.flush(first)
        with pytest.raises(AuditRegistryUnavailable):
            await barrier.flush(UsageLedger())
    finally:
        barrier.close()
    assert not first._observers
