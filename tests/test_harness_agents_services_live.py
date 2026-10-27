"""Real backend/agents/workspace; only provider HTTP transport is scripted."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(
    os.getenv("HARNESS_AGENTS_SERVICES_LIVE") != "1", reason="isolated agents opt-in"
)
@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai"])
def test_common_loop_creates_file_and_verifies_command_on_real_services(provider):
    assert run_command_probe(agents=True, provider=provider)["agents_harness_verified"]


@pytest.mark.skipif(
    os.getenv("HARNESS_AGENTS_SERVICES_LIVE") != "1", reason="isolated agents opt-in"
)
@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai"])
def test_common_loop_repairs_failed_check_on_real_services(provider):
    outcome = run_command_probe(agents=True, scenario="repair", provider=provider)
    assert outcome["agents_harness_verified"] and outcome["repair_verified"]
