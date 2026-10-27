"""PDF: настоящий renderer/workspace/compiler, только model HTTP подменён."""

import os

import pytest

from scripts.harness.live.host import run_command_probe


@pytest.mark.skipif(
    os.getenv("HARNESS_DOCUMENT_SERVICES_LIVE") != "1", reason="isolated PDF opt-in"
)
@pytest.mark.parametrize("fault", ["", "document_acks"])
def test_structural_review_applies_three_slides_and_builds_current_pdf_once(fault):
    outcome = run_command_probe(agents=True, scenario="pdf_review", workspace_fault=fault)
    assert outcome["actual_pdf_verified"] and outcome["build_replay_unchanged"]
    assert outcome["resume_scope_verified"]
    assert not outcome["automatic_apply"] and not outcome["worker_covered"]
