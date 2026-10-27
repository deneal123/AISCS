"""Только model transport — double; worker, snapshots, команда, journal и settlement реальные."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(
    os.getenv("HARNESS_REFINEMENT_SERVICES_LIVE") != "1", reason="isolated refinement opt-in"
)
def test_worker_adopts_verified_instruction_and_replays_without_effects_or_charges():
    result = run_command_probe(agents=True, worker=True, scenario="refine")
    assert result["instruction_refinement_verified"] and result["charges"] == 1
    assert result["redelivery_unchanged"] and result["restart_redelivery_unchanged"]


@pytest.mark.skipif(
    os.getenv("HARNESS_REFINEMENT_SERVICES_LIVE") != "1", reason="isolated refinement opt-in"
)
@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai"])
def test_refinement_preserves_provider_protocol_and_completion_guards(provider):
    result = run_command_probe(agents=True, scenario="refine", provider=provider)
    assert result["instruction_refinement_verified"] and result["agents_harness_verified"]
