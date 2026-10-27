"""Настоящий agents restart с обрывом /run и доставкой того же задания."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(
    os.getenv("HARNESS_WORKER_SERVICES_LIVE") != "1", reason="isolated worker opt-in"
)
def test_interrupted_agents_process_recovers_without_replaying_paid_or_project_effects():
    assert run_command_probe(agents=True, worker=True, agents_restart=True)[
        "agents_restart_recovered"
    ]


@pytest.mark.skipif(
    os.getenv("HARNESS_WORKER_SERVICES_LIVE") != "1", reason="isolated worker opt-in"
)
def test_stop_between_retry_intent_and_delivery_settles_without_new_model_or_command():
    assert run_command_probe(agents=True, worker=True, agents_restart=True, restart_stop=True)[
        "agents_restart_stopped"
    ]


@pytest.mark.skipif(
    os.getenv("HARNESS_WORKER_SERVICES_LIVE") != "1", reason="Нужен изолированный worker-стенд"
)
def test_stop_after_grant_before_first_dispatch_settles_zero_without_fictitious_receipts():
    assert run_command_probe(agents=True, worker=True, stop_before_dispatch=True)[
        "stop_before_dispatch_verified"
    ]


@pytest.mark.skipif(
    os.getenv("HARNESS_WORKER_SERVICES_LIVE") != "1", reason="Нужен изолированный worker-стенд"
)
def test_exhausted_agents_recovery_settles_confirmed_receipts_once_without_replaying_effects():
    assert run_command_probe(
        agents=True, worker=True, agents_restart=True, restart_exhausted="after_write"
    )["agents_restart_exhausted"]


@pytest.mark.skipif(
    os.getenv("HARNESS_WORKER_SERVICES_LIVE") != "1", reason="Нужен изолированный worker-стенд"
)
def test_exhaustion_before_first_dispatch_settles_zero_without_fictitious_receipts():
    assert run_command_probe(
        agents=True, worker=True, agents_restart=True, restart_exhausted="before_dispatch"
    )["agents_restart_exhausted"]
