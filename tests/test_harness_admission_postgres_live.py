"""Предконтрактное продолжение через реальный PG repository; не worker E2E."""

import os

import pytest

from tests.harness_postgres import run_probe


@pytest.mark.skipif(os.getenv("HARNESS_RUNTIME_LIVE") != "1", reason="disposable runtime PG opt-in")
def test_unsealed_question_handoff_and_seal_survive_repository_restart():
    result = run_probe(
        "admission_pause",
        [
            "alembic/versions/043_harness_state.py",
            "alembic/versions/044_harness_runtime.py",
            "alembic/versions/045_harness_reservation_retention.py",
            "service/shared/harness_protocol.py",
            "service/shared/task_contract.py",
            "service/services/chat/persistence/harness/runtime.py",
            "service/services/chat/persistence/harness/admission_checkpoint.py",
            "service/services/chat/persistence/harness/admission/calls.py",
            "service/services/chat/persistence/harness/model_requests.py",
            "service/services/chat/persistence/harness/inspection.py",
            "service/services/chat/persistence/harness/rebind.py",
            "service/services/chat/persistence/harness/grants.py",
            "service/services/chat/persistence/harness/state.py",
            "service/services/chat/persistence/harness/reservations.py",
        ],
    )
    assert result == {
        "cases": [
            "committed_question_receipt",
            "durable_unsealed_pause",
            "unsealed_effect_denied",
            "unanswered_seal_denied",
            "child_handoff_and_parent_fencing",
            "answer_persisted_at_seal",
            "active_time_provider_and_usage_preserved",
            "mandatory_verification_retained",
            "two_contract_calls_per_information_window",
            "root_and_child_third_call_denied",
            "wire_digest_and_repeated_grant_preserved",
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
