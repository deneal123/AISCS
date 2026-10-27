"""Opt-in real backend HTTP, PostgreSQL, storage and scoped workspace/Engine."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(
    os.getenv("HARNESS_CONSOLE_SERVICES_LIVE") != "1", reason="isolated services opt-in"
)
def test_real_console_snapshot_and_once_only_command_receipt():
    assert run_command_probe()["command_verified"] is True


@pytest.mark.skipif(
    os.getenv("HARNESS_CONSOLE_SERVICES_LIVE") != "1", reason="isolated services opt-in"
)
def test_invalid_command_refusal_retires_intent_before_a_corrected_new_operation():
    assert run_command_probe(invalid_arguments=True)["invalid_arguments_reconciled"]


@pytest.mark.skipif(
    os.getenv("HARNESS_CONSOLE_SERVICES_LIVE") != "1", reason="isolated services opt-in"
)
def test_lost_workspace_go_ack_reconciles_the_same_engine_instance():
    assert run_command_probe(workspace_fault="dispatch_ack")["command_verified"] is True


@pytest.mark.skipif(
    os.getenv("HARNESS_CONSOLE_SERVICES_LIVE") != "1", reason="isolated services opt-in"
)
@pytest.mark.parametrize("action", ["complete", "stop"])
def test_workspace_restart_reconciles_cleanup_but_never_invents_lost_output(action):
    assert run_command_probe(workspace_fault="restart_" + action)["workspace_restart_verified"]
