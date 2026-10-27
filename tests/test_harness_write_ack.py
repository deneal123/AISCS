"""A lost write ACK may change only the backend-owned proof version, not its facts."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.infrastructure.harness.reconciliation import reconcile_exchange
from service.shared.harness_protocol import EffectResult, Exchange, Snapshot
from service.shared.task_contract import TaskEvidence
from tests.test_harness_reconciliation import current


def case():
    prior = current()
    operation_id = str(uuid4())
    proof = TaskEvidence(
        criterion_id="source",
        operation_id=operation_id,
        kind="file",
        target="a.py",
        source_revision=prior.state.source_revision,
        digest="a" * 64,
        outcome="passed",
    )
    submitted = EffectResult(
        operation_id=operation_id,
        status="succeeded",
        text='{"written":true}',
        charged=True,
        evidence=[proof],
    )
    revision = "write:" + operation_id
    recorded = submitted.model_copy(
        update={"evidence": (proof.model_copy(update={"source_revision": revision}),)}
    )
    state = prior.state.advance(source_revision=revision, evidence=recorded.evidence)
    latest = Snapshot(
        admission=prior.admission,
        revision=prior.revision + 1,
        state=state,
        continuation=prior.continuation,
    )
    return prior, submitted, recorded, latest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [None, "digest", "charged", "text", "user_edit", "rounds", "stopped", "missing_evidence"],
)
async def test_exact_normalized_receipt_restores_the_backend_snapshot_or_remains_blocked(change):
    prior, submitted, recorded, latest = case()
    if change == "digest":
        recorded = recorded.model_copy(
            update={"evidence": (recorded.evidence[0].model_copy(update={"digest": "b" * 64}),)}
        )
    if change in {"charged", "text"}:
        recorded = recorded.model_copy(
            update={change: False if change == "charged" else "different"}
        )
    if change in {"user_edit", "rounds", "missing_evidence"}:
        update = (
            {"source_revision": "user-edit"}
            if change == "user_edit"
            else {"rounds": 4}
            if change == "rounds"
            else {"evidence": []}
        )
        latest = latest.model_copy(update={"state": latest.state.advance(**update)})
    if change == "stopped":
        latest = latest.model_copy(update={"stopped": True})
    query = AsyncMock(
        side_effect=[
            {
                "operation_status": {
                    "operation_id": submitted.operation_id,
                    "operation_kind": "effect",
                    "status": "succeeded",
                    "request_digest": "b" * 64,
                    "receipt": recorded.model_dump(mode="json"),
                }
            },
            {"snapshot": latest.model_dump(mode="json")},
        ]
    )
    result = await reconcile_exchange(
        Exchange(opcode="effect_receipt", effect_result=submitted), prior, query
    )
    if change is None:
        assert result["snapshot"] == latest.model_dump(mode="json")
        assert result["operation"]["receipt"] == recorded.model_dump(mode="json")
    else:
        assert result is None
    assert query.await_args_list[0].kwargs["opcode"] == "operation_status"


@pytest.mark.asyncio
async def test_supporting_write_without_a_completion_criterion_still_restores_its_version():
    prior, submitted, recorded, latest = case()
    submitted = submitted.model_copy(update={"evidence": ()})
    recorded = recorded.model_copy(update={"evidence": ()})
    latest = latest.model_copy(update={"state": latest.state.advance(evidence=[])})
    query = AsyncMock(
        side_effect=[
            {
                "operation_status": {
                    "operation_id": submitted.operation_id,
                    "operation_kind": "effect",
                    "status": "succeeded",
                    "request_digest": "a" * 64,
                    "receipt": recorded.model_dump(mode="json"),
                }
            },
            {"snapshot": latest.model_dump(mode="json")},
        ]
    )
    result = await reconcile_exchange(
        Exchange(opcode="effect_receipt", effect_result=submitted), prior, query
    )
    assert result["snapshot"] == latest.model_dump(mode="json")
    assert not result["snapshot"]["state"]["evidence"]


@pytest.mark.asyncio
async def test_write_ack_recovery_keeps_the_backend_cost_hold():
    from service.shared.task_contract import CompletionVerifier

    prior, submitted, recorded, latest = case()
    latest = latest.model_copy(
        update={
            "held_credits": 99,
            "state": latest.state.advance(budget={"spent_credits": 0, "held_credits": 99}),
        }
    )
    query = AsyncMock(
        side_effect=[
            {
                "operation_status": {
                    "operation_id": submitted.operation_id,
                    "operation_kind": "effect",
                    "status": "succeeded",
                    "request_digest": "a" * 64,
                    "receipt": recorded.model_dump(mode="json"),
                }
            },
            {"snapshot": latest.model_dump(mode="json")},
        ]
    )
    result = await reconcile_exchange(
        Exchange(opcode="effect_receipt", effect_result=submitted), prior, query
    )
    recovered = Snapshot.model_validate(result["snapshot"])
    assert recovered.held_credits == recovered.state.budget.held_credits == 99
    assert CompletionVerifier.evaluate(recovered.state)["blocker"] == "cost_unknown"
