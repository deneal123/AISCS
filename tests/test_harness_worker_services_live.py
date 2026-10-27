"""Actual Celery lifecycle; only the agents model HTTP transport is scripted."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(
    os.getenv("HARNESS_WORKER_SERVICES_LIVE") != "1", reason="isolated worker opt-in"
)
@pytest.mark.parametrize(
    "ack_fault",
    [
        "",
        "checkpoint",
        "file_receipt",
        "paid_receipt",
        "paid_receipt_unavailable",
        "stream_receipt_unavailable",
    ],
)
def test_worker_reserves_executes_settles_and_short_circuits_redelivery(ack_fault):
    assert run_command_probe(agents=True, worker=True, ack_fault=ack_fault)[
        "worker_harness_verified"
    ]


@pytest.mark.skipif(
    os.getenv("HARNESS_WORKER_SERVICES_LIVE") != "1", reason="isolated worker opt-in"
)
@pytest.mark.parametrize("boundary", ["checkpoint", "provider_receipt"])
def test_prefork_sigkill_resumes_the_unfinished_task_without_repeating_effects(boundary):
    assert run_command_probe(agents=True, worker=True, worker_crash=True, crash_boundary=boundary)[
        "worker_crash_recovered"
    ]


@pytest.mark.skipif(
    os.getenv("HARNESS_WORKER_SERVICES_LIVE") != "1", reason="isolated worker opt-in"
)
def test_prefork_resume_after_tuning_change_reuses_the_original_paid_receipt():
    outcome = run_command_probe(
        agents=True,
        worker=True,
        worker_crash=True,
        crash_boundary="provider_receipt",
        resume_tuning=True,
    )
    assert outcome["worker_crash_recovered"] and outcome["completed_slot_reused"]


@pytest.mark.skipif(
    os.getenv("HARNESS_WORKER_SERVICES_LIVE") != "1", reason="isolated worker opt-in"
)
def test_authenticated_stop_cleans_running_user_code_and_releases_the_mutation_gate():
    assert run_command_probe(agents=True, worker=True, worker_stop=True, scenario="stop")[
        "worker_stop_verified"
    ]


@pytest.mark.skipif(
    os.getenv("HARNESS_WORKER_SERVICES_LIVE") != "1", reason="isolated worker opt-in"
)
def test_worker_reconciles_lost_workspace_dispatch_ack_without_a_second_exec():
    assert run_command_probe(agents=True, worker=True, workspace_fault="dispatch_ack")[
        "worker_harness_verified"
    ]
