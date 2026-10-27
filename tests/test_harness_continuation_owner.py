"""The checkpoint owner cannot be replaced by a fresh routing decision."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.persistence.harness.runtime import _checkpoint, _sealed_state
from service.shared.harness_protocol import (
    Admission,
    Continuation,
    ContractProposal,
    Exchange,
    HarnessFailure,
    Snapshot,
)
from tests.test_harness_runtime_contract import admission


@pytest.mark.asyncio
@pytest.mark.parametrize("new_owner", [None, "other"])
async def test_checkpoint_cannot_remove_or_replace_frozen_agent(new_owner):
    accepted = admission()
    state = _sealed_state(
        Snapshot(admission=accepted),
        ContractProposal(
            kind="change", criteria=[{"criterion_id": "source", "kind": "file", "target": "a.py"}]
        ),
    )
    current = Snapshot(
        admission=accepted,
        state=state,
        continuation=Continuation(agent_name="general", phase="model"),
    )
    request = Exchange(
        opcode="checkpoint",
        expected_revision=0,
        continuation=Continuation(agent_name=new_owner, phase="model"),
    )
    db = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock())
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        await _checkpoint(db, {"task_id": uuid4()}, request, current)
    db.execute.assert_not_awaited()
    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["ide", "pdf"])
async def test_checkpoint_cannot_attest_a_new_source_revision_in_either_surface(surface):
    accepted = Admission.model_validate(
        {
            **admission().model_dump(mode="json"),
            "surface": surface,
            "actions": ["read", "write", "exec"] if surface == "ide" else ["read", "document"],
        }
    )
    state = _sealed_state(
        Snapshot(admission=accepted),
        ContractProposal(
            kind="change" if surface == "ide" else "document",
            criteria=[
                {
                    "criterion_id": "source",
                    "kind": "file" if surface == "ide" else "pdf",
                    "target": "a.py" if surface == "ide" else "documents/paper",
                }
            ],
        ),
    )
    continuation = Continuation(agent_name="general", phase="model", call_payload_version=2)
    current = Snapshot(admission=accepted, state=state, continuation=continuation)
    request = Exchange(
        opcode="checkpoint",
        expected_revision=0,
        continuation=continuation,
        state=state.advance(source_revision="not-an-executor-receipt"),
    )
    db = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock())
    with pytest.raises(HarnessFailure, match="binding_changed"):
        await _checkpoint(db, {"task_id": uuid4()}, request, current)
    db.execute.assert_not_awaited()
    db.scalar.assert_not_awaited()
