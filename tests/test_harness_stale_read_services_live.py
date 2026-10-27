"""Реальная пользовательская правка на барьере, только model HTTP подменён."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(os.getenv("HARNESS_STALE_READ_LIVE") != "1", reason="Worker opt-in")
@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai"])
def test_ui_edit_retires_read_evidence_without_overwrite_or_second_settlement(provider):
    outcome = run_command_probe(agents=True, worker=True, scenario="read_change", provider=provider)
    assert outcome["stale_read_blocked"] and outcome["user_edit_preserved"]
