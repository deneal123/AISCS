"""Настоящие PG-транзакции, без модели, workspace или списания пользователю."""

import os

import pytest

from tests.harness_postgres import run_probe


@pytest.mark.skipif(os.getenv("HARNESS_RUNTIME_LIVE") != "1", reason="disposable PG opt-in")
def test_concurrent_changed_model_requests_share_one_continuation_slot():
    outcome = run_probe(
        "request_freeze",
        [
            "alembic/versions/043_harness_state.py",
            "alembic/versions/044_harness_runtime.py",
            "alembic/versions/045_harness_reservation_retention.py",
            "service/shared/harness_protocol.py",
            "service/shared/task_contract.py",
            "service/services/chat/persistence/harness/runtime.py",
            "service/services/chat/persistence/harness/grants.py",
            "service/services/chat/persistence/harness/model_requests.py",
            "service/services/chat/persistence/harness/model_replay.py",
            "service/services/chat/persistence/harness/state.py",
        ],
    )
    assert outcome == {
        "cases": [
            "one_request_per_step",
            "frozen_body_persisted",
            "changed_request_no_dispatch",
            "receipt_and_budget_unchanged",
            "completed_slot_replay_original_id",
            "codec_transition_fenced",
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
