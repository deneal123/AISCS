"""Exact usage refines one accepted estimated call, never another identity."""

from dataclasses import replace

import pytest

from service.domain.usage.ledger import UsageLedger, UsageReceipt


def test_exact_usage_replaces_estimate_without_another_receipt():
    ledger = UsageLedger()
    estimate = UsageReceipt("call", "openai", "synthetic", 100, 20, estimated=True)
    exact = replace(estimate, prompt=97, completion=24, estimated=False)
    assert ledger.record(estimate)
    assert ledger.record(exact)
    assert ledger.receipts == (exact,)
    assert ledger.cursor() == 1
    assert not ledger.record(exact)
    assert not ledger.record(estimate)
    assert ledger.receipts == (exact,)


@pytest.mark.parametrize(
    "changed", [{"provider": "other"}, {"model": "other"}, {"kind": "meta_usage"}]
)
def test_placeholder_cannot_change_call_provenance(changed):
    ledger = UsageLedger()
    accepted = UsageReceipt("call", "openai", "synthetic", 0, 0)
    foreign = replace(accepted, prompt=20, completion=2, **changed)
    assert ledger.record(accepted)
    assert not ledger.record(foreign)
    assert ledger.receipts == (accepted,)


def test_refinement_keeps_explicit_nonchargeable_decision():
    ledger = UsageLedger()
    estimate = UsageReceipt("call", "openai", "synthetic", 100, 20, estimated=True)
    ledger.record(estimate)
    ledger.set_chargeable("call", False)
    exact = replace(estimate, prompt=97, completion=24, estimated=False)
    assert ledger.record(exact)
    assert ledger.receipts == (replace(exact, chargeable=False),)
    assert not ledger.receipts[0].billable


def test_model_runtime_projection_returns_canonical_not_rejected_replay():
    ledger = UsageLedger()
    accepted = ledger.record_usage(
        {"prompt": 100, "completion": 20, "estimated": True},
        provider="openai",
        model="synthetic",
        receipt_id="call",
    )
    ledger.set_chargeable(accepted.receipt_id, False)
    refined = ledger.record_usage(
        {"prompt": 97, "completion": 24},
        provider="openai",
        model="synthetic",
        receipt_id="call",
    )
    assert refined == ledger.receipts[0]
    assert not refined.chargeable
    replay = ledger.record_usage(
        {"prompt": 1000, "completion": 200},
        provider="other",
        model="other",
        receipt_id="call",
    )
    assert replay == refined
    assert ledger.receipts == (refined,)
