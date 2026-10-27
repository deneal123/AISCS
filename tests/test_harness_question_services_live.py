"""Настоящий HTTP/worker/outbox/workspace; подменяется только транспорт модели."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(
    os.getenv("HARNESS_QUESTION_SERVICES_LIVE") != "1", reason="isolated question opt-in"
)
def test_precontract_question_answer_outbox_completion_and_redelivery():
    assert run_command_probe(agents=True, worker=True, scenario="clarify")[
        "question_harness_verified"
    ]


@pytest.mark.skipif(
    os.getenv("HARNESS_QUESTION_SERVICES_LIVE") != "1", reason="isolated question opt-in"
)
@pytest.mark.parametrize(
    "mode", ["cancel", "expiry", "stop_child", "cost_decline", "cost_expiry", "cost_ack"]
)
def test_question_boundaries_never_dispatch_without_current_decision(mode):
    outcome = run_command_probe(
        agents=True,
        worker=True,
        scenario="clarify",
        question_boundary=mode,
        ack_fault="question_cost" if mode == "cost_ack" else "",
    )
    assert outcome["question_boundary_verified"] == mode


@pytest.mark.skipif(
    os.getenv("HARNESS_QUESTION_SERVICES_LIVE") != "1", reason="isolated question opt-in"
)
@pytest.mark.parametrize("ack_fault", ["checkpoint", "paid_receipt"])
def test_question_recovers_committed_checkpoint_and_usage_ack_without_repeat(ack_fault):
    assert run_command_probe(agents=True, worker=True, scenario="clarify", ack_fault=ack_fault)[
        "question_harness_verified"
    ]
