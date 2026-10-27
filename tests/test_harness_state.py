"""Checkpoint transitions cannot weaken a task or invent executor receipts."""

from uuid import uuid4

import pytest

from service.services.chat.domain.harness_state import (
    HarnessCheckpoint,
    OperationIntent,
    OperationReceipt,
    ProviderBinding,
    receipt_matches,
    valid_checkpoint_transition,
)
from tests.test_task_contract import evidence, state


def test_resume_cannot_weaken_contract_reset_counters_or_switch_provider():
    old = HarnessCheckpoint(state=state(rounds=8, repairs=1, protocol_repairs=1))
    good = HarnessCheckpoint(state=old.state.claim_round())
    assert valid_checkpoint_transition(old, good)
    for change in [{"rounds": 0}, {"repairs": 0}, {"protocol_repairs": 0}]:
        assert not valid_checkpoint_transition(
            old, HarnessCheckpoint(state=old.state.advance(**change))
        )
    weaker = old.state.contract.model_dump(mode="json")
    weaker["criteria"] = weaker["criteria"][:1]
    assert not valid_checkpoint_transition(
        old, HarnessCheckpoint(state=old.state.advance(contract=weaker))
    )
    bound = HarnessCheckpoint(
        state=old.state, provider=ProviderBinding(provider="openai", model="a")
    )
    switched = HarnessCheckpoint(
        state=good.state, provider=ProviderBinding(provider="openai", model="b")
    )
    assert not valid_checkpoint_transition(bound, switched)
    assert not valid_checkpoint_transition(bound, good)


def test_checkpoint_cannot_remove_unknown_cost_or_previous_evidence():
    old = HarnessCheckpoint(state=state(budget={"held_credits": 1}, evidence=[evidence()]))
    cleared = HarnessCheckpoint(state=old.state.advance(budget={"held_credits": 0}))
    assert not valid_checkpoint_transition(old, cleared)
    removed = HarnessCheckpoint(state=old.state.advance(evidence=[]))
    assert not valid_checkpoint_transition(old, removed)


def test_receipt_must_match_operation_criterion_file_and_result_version():
    current = state()
    intent = OperationIntent(
        operation_id=str(uuid4()),
        kind="tool",
        action="write",
        name="ide_write_file",
        request_digest="b" * 64,
        source_revision="r1",
        criterion_ids=["source"],
    )
    proof = evidence(operation_id=intent.operation_id, source_revision="r2")
    receipt = OperationReceipt(status="succeeded", result_revision="r2", evidence=[proof])
    assert receipt_matches(intent, receipt, current)
    for patch in [
        {"operation_id": str(uuid4())},
        {"target": "other.py"},
        {"source_revision": "r0"},
        {"criterion_id": "test", "kind": "command", "exit_code": 0},
    ]:
        wrong = evidence(**{**proof.model_dump(), **patch})
        assert not receipt_matches(
            intent,
            OperationReceipt(status="succeeded", result_revision="r2", evidence=[wrong]),
            current,
        )


def test_unknown_receipt_cannot_contain_successful_evidence():
    with pytest.raises(ValueError):
        OperationReceipt(status="unknown", evidence=[evidence()])
