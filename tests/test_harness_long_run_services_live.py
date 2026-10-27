"""Реальные шесть файлов и команда на границе16 раундов, model HTTP — double."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(os.getenv("HARNESS_LONG_RUN_LIVE") != "1", reason="isolated 16-round opt-in")
@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai"])
def test_sixteen_rounds_complete_multifile_project_on_real_services(provider):
    outcome = run_command_probe(agents=True, scenario="long", provider=provider)
    assert outcome["sixteen_rounds_verified"] and outcome["rounds"] == 16
