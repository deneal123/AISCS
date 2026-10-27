"""Deterministic criterion-specific completion and immutable task limit regressions."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from service.shared.task_contract import (
    CompletionVerifier,
    TaskContract,
    TaskEvidence,
    TaskResultV2,
    TaskState,
)


def state(**overrides):
    contract = {
        "task_id": str(uuid4()),
        "project_id": "project",
        "generation": "generation",
        "goal": "PRIVATE_GOAL",
        "kind": "change",
        "actions": ["read", "write", "exec"],
        "criteria": [
            {"criterion_id": "source", "kind": "file", "target": "src/hello_world.py"},
            {"criterion_id": "test", "kind": "command", "target": "src/hello_world.py"},
        ],
        "credit_limit": 100,
    }
    return TaskState.model_validate(
        {
            "contract": contract,
            "source_revision": "r1",
            **overrides,
        }
    )


def evidence(criterion="source", **overrides):
    return TaskEvidence.model_validate(
        {
            "criterion_id": criterion,
            "operation_id": str(uuid4()),
            "kind": "file" if criterion == "source" else "command",
            "target": "src/hello_world.py",
            "source_revision": "r1",
            "digest": "a" * 64,
            "outcome": "passed",
            "exit_code": 0 if criterion == "test" else None,
            **overrides,
        }
    )


def test_all_mandatory_criteria_require_current_revision_receipts():
    current = state()
    assert CompletionVerifier.evaluate(current)["unchecked"] == ["source", "test"]
    written = current.advance(evidence=[evidence().model_dump(mode="json")])
    assert CompletionVerifier.evaluate(written)["unchecked"] == ["test"]
    verified = written.advance(evidence=[*written.evidence, evidence("test")])
    result = CompletionVerifier.evaluate(verified)
    assert result["status"] == "completed" and result["verified"]
    assert TaskResultV2.model_validate(result)
    assert "PRIVATE_GOAL" not in str(result)
    edited = verified.advance(source_revision="r2")
    assert CompletionVerifier.evaluate(edited)["unchecked"] == ["source", "test"]


def test_file_b_cannot_close_criterion_for_file_a():
    current = state()
    with pytest.raises(ValidationError, match="task_evidence_wrong_target"):
        current.advance(evidence=[evidence(target="src/unrelated.py")])


def test_analysis_does_not_require_a_file_write():
    current = state()
    contract = {
        **current.contract.model_dump(mode="json"),
        "kind": "analysis",
        "actions": ["read"],
        "criteria": [{"criterion_id": "source", "kind": "read", "target": "README.md"}],
    }
    analysis = TaskState.model_validate(
        {
            "contract": contract,
            "source_revision": "r1",
            "evidence": [evidence(kind="read", target="README.md").model_dump(mode="json")],
        }
    )
    assert CompletionVerifier.evaluate(analysis)["status"] == "completed"


@pytest.mark.parametrize(
    "change",
    [
        {"rounds": 17},
        {"repairs": 3},
        {"protocol_repairs": 2},
        {"rounds": True},
        {"budget": {"spent_credits": 70, "held_credits": 31}},
        {"budget": {"active_ms": 570001}},
    ],
)
def test_limits_are_revalidated_on_every_advance(change):
    with pytest.raises(ValidationError):
        state().advance(**change)


def test_round_limit_survives_serialization_and_resume():
    current = state()
    for _ in range(16):
        current = TaskState.model_validate_json(current.claim_round().model_dump_json())
    assert current.rounds == 16
    with pytest.raises(ValidationError):
        current.claim_round()


def test_contract_is_deeply_immutable_and_invalid_uuid_is_rejected():
    current = state()
    assert isinstance(current.contract.actions, tuple)
    assert isinstance(current.contract.criteria, tuple)
    with pytest.raises(ValidationError):
        current.contract.round_limit = 17
    with pytest.raises(ValidationError):
        TaskContract.model_validate({**current.contract.model_dump(), "task_id": "-" * 36})


@pytest.mark.parametrize(
    "outcome,blocker",
    [
        ("failed", "verification_failed"),
        ("unknown", "operation_unknown"),
    ],
)
def test_latest_failed_or_unknown_receipt_cannot_be_hidden(outcome, blocker):
    current = state(evidence=[evidence(), evidence("test"), evidence("test", outcome=outcome)])
    assert CompletionVerifier.evaluate(current)["blocker"] == blocker


def test_unknown_cost_stays_a_blocker_even_with_all_evidence():
    current = state(evidence=[evidence(), evidence("test")], budget={"held_credits": 1})
    assert CompletionVerifier.evaluate(current)["blocker"] == "cost_unknown"
    assert not CompletionVerifier.evaluate(current)["verified"]


def test_successful_command_with_wrong_expected_output_is_not_verified():
    current = state(evidence=[evidence(), evidence("test")])
    contract = current.contract.model_dump(mode="json")
    contract["criteria"][1]["expected_digest"] = "b" * 64
    current = current.advance(contract=contract)
    assert CompletionVerifier.evaluate(current)["blocker"] == "verification_failed"
    assert CompletionVerifier.evaluate(current)["unchecked"] == ["test"]


def test_in_flight_operation_blocks_completion_even_with_previous_successes():
    current = state(evidence=[evidence(), evidence("test")])
    assert (
        CompletionVerifier.evaluate(current, pending_operations=True)["blocker"]
        == "operation_unknown"
    )


def test_cancelled_task_cannot_consume_a_round_or_be_successful():
    current = state(cancelled=True, evidence=[evidence(), evidence("test")])
    with pytest.raises(ValueError, match="task_cancelled"):
        current.claim_round()
    assert CompletionVerifier.evaluate(current)["status"] == "cancelled"


def test_pdf_requires_real_artifact_and_current_source_revision():
    with pytest.raises(ValidationError, match="artifact_not_confirmed"):
        evidence(kind="pdf")
    current = state()
    contract = {
        **current.contract.model_dump(mode="json"),
        "kind": "document",
        "actions": ["document"],
        "criteria": [{"criterion_id": "source", "kind": "pdf", "target": "main.tex"}],
    }
    document = TaskState.model_validate(
        {
            "contract": contract,
            "source_revision": "r1",
            "evidence": [
                evidence(kind="pdf", target="main.tex", artifact_id="artifact").model_dump()
            ],
        }
    )
    assert CompletionVerifier.evaluate(document)["verified"]
    assert not CompletionVerifier.evaluate(document.advance(source_revision="r2"))["verified"]


def test_duplicate_operation_evidence_cannot_be_counted_twice():
    receipt = evidence()
    with pytest.raises(ValidationError, match="task_evidence_duplicate"):
        state(evidence=[receipt, receipt])


@pytest.mark.parametrize(
    "change",
    [
        {"verified": False},
        {"unchecked": ["test"]},
        {"blocker": "operation_unknown"},
        {"transcript": "PRIVATE"},
        {"references": []},
    ],
)
def test_public_completion_projection_is_closed_and_consistent(change):
    result = CompletionVerifier.evaluate(state(evidence=[evidence(), evidence("test")]))
    with pytest.raises(ValidationError):
        TaskResultV2.model_validate({**result, **change})
