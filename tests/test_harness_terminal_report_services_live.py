"""Реальные IDE effects и восстановление отчёта; только provider HTTP — double."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(
    os.getenv("HARNESS_TERMINAL_REPORT_LIVE") != "1", reason="isolated report opt-in"
)
@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai"])
def test_skipped_report_uses_new_slot_and_shared_limits_on_real_services(provider):
    outcome = run_command_probe(agents=True, scenario="finish", provider=provider)
    assert outcome["terminal_report_repair_verified"] and outcome["agents_harness_verified"]
