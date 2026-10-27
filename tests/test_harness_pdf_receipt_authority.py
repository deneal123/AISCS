"""Предложение правок не становится доказательством собранного PDF."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.persistence.harness import effects
from service.services.chat.persistence.harness.runtime import _sealed_state
from service.shared.harness_protocol import (
    Admission,
    ContractProposal,
    EffectIntent,
    EffectResult,
    HarnessFailure,
    Snapshot,
)
from service.shared.task_contract import TaskEvidence
from tests.test_harness_runtime_contract import admission


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["tex_propose_patch", "tex_propose_structure"])
async def test_adapter_cannot_attest_compiled_pdf_from_review_proposal(monkeypatch, name):
    accepted = Admission.model_validate(
        {
            **admission().model_dump(mode="json"),
            "surface": "pdf",
            "actions": ["read", "document"],
        }
    )
    state = _sealed_state(
        Snapshot(admission=accepted),
        ContractProposal(
            kind="document",
            criteria=[
                {"criterion_id": "document", "kind": "pdf", "target": "documents/cats"},
            ],
        ),
    )
    current = Snapshot(admission=accepted, state=state)
    operation_id = str(uuid4())
    intent = EffectIntent(
        operation_id=operation_id,
        name=name,
        action="document",
        arguments="{}",
        source_revision=state.source_revision,
    )
    existing = {"intent": intent.model_dump(mode="json"), "status": "dispatched", "receipt": None}
    monkeypatch.setattr(effects, "read", AsyncMock(return_value=existing))
    proof = TaskEvidence(
        criterion_id="document",
        operation_id=operation_id,
        kind="pdf",
        target="documents/cats",
        digest="a" * 64,
        outcome="passed",
        source_revision=state.source_revision,
        artifact_id="invented-artifact",
    )
    receipt = EffectResult(
        operation_id=operation_id,
        status="succeeded",
        text="awaiting_review",
        evidence=[proof],
        charged=True,
    )
    db = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock())
    with pytest.raises(HarnessFailure, match="verification_missing"):
        await effects.record(db, {"task_id": uuid4()}, receipt, current)
    db.execute.assert_not_awaited()
