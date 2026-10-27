"""Настоящий PG, синтетические model/executor receipts; не полный worker acceptance."""

import os

import pytest

from tests.harness_postgres import run_probe


@pytest.mark.skipif(os.getenv("HARNESS_RUNTIME_LIVE") != "1", reason="disposable runtime PG opt-in")
def test_refinement_origin_verified_adoption_and_reload():
    assert run_probe(
        "refinement_probe",
        [
            "service/shared/harness_protocol.py",
            "service/shared/harness_refinement.py",
            "service/services/chat/persistence/harness/refinement.py",
            "service/services/chat/persistence/harness/lessons.py",
            "service/services/chat/persistence/harness/runtime.py",
            "service/services/chat/persistence/harness/result.py",
        ],
    ) == {
        "cases": [
            "candidate_reloaded",
            "self_adoption_rejected",
            "pending_not_adopted",
            "verified_adopted",
            "repeat_unchanged",
            "lesson_requires_final_task_result",
            "lesson_user_project_generation_scope",
            "unused_guidance_not_adopted",
            "unused_guidance_not_reused",
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
