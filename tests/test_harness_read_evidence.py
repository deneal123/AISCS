"""Чтение попадает в authoritative snapshot, не теряется после receipt ACK."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from service.services.chat.persistence.harness.commands import write_versions
from service.shared.harness_protocol import Continuation, EffectResult, HarnessFailure
from service.shared.task_contract import CompletionVerifier, TaskState
from tests.test_task_contract import evidence, state


def scenario(*, already=False, revision="r1", status="succeeded"):
    base = state()
    proof = evidence(kind="read")
    current = base.advance(
        contract={
            **base.contract.model_dump(mode="json"),
            "kind": "analysis",
            "actions": ["read"],
            "criteria": [{"criterion_id": "source", "kind": "read", "target": proof.target}],
        },
        source_revision=revision,
        evidence=[proof] if already else [],
    )
    receipt = EffectResult(
        operation_id=proof.operation_id,
        status=status,
        text="Прочитано",
        evidence=[proof] if status == "succeeded" else [],
        charged=None if status == "unknown" else status == "succeeded",
    )
    return current, receipt


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["new", "duplicate", "stale", "failed", "unknown", "rejected"])
async def test_valid_read_is_committed_once_without_minting_or_rebasing_proofs(monkeypatch, case):
    current, receipt = scenario(
        already=case == "duplicate",
        revision="r2" if case == "stale" else "r1",
        status=case if case in {"failed", "unknown"} else "succeeded",
    )
    monkeypatch.setattr(
        write_versions.effects,
        "read",
        AsyncMock(
            return_value={
                "intent": {"action": "read", "name": "ide_read_file"},
                "receipt": None,
            }
        ),
    )
    record = AsyncMock(return_value={"status": receipt.status})
    if case == "rejected":
        record.side_effect = HarnessFailure("verification_missing")
    monkeypatch.setattr(write_versions.effects, "record", record)
    db = SimpleNamespace(execute=AsyncMock())
    owner = SimpleNamespace(
        state=current,
        admission=SimpleNamespace(surface="ide"),
        continuation=Continuation(),
    )
    args = (db, {"task_id": UUID(current.contract.task_id)}, receipt, owner)
    if case == "rejected":
        with pytest.raises(HarnessFailure):
            await write_versions.accept_effect(*args)
    else:
        assert await write_versions.accept_effect(*args) == {"status": receipt.status}
    record.assert_awaited_once()
    if case == "new":
        db.execute.assert_awaited_once()
        saved = TaskState.model_validate(json.loads(db.execute.await_args.args[1]["body"])["state"])
        assert CompletionVerifier.evaluate(saved)["status"] == "completed"
        assert saved.source_revision == current.source_revision
        assert saved.evidence == receipt.evidence and saved.revision == current.revision + 1
    else:
        db.execute.assert_not_awaited()
