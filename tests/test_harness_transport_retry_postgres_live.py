"""Реальные транзакции и утраченный ACK, только одноразовая dev-БД."""

import os

import pytest

from tests.harness_postgres import run_probe


@pytest.mark.skipif(os.getenv("HARNESS_RUNTIME_LIVE") != "1", reason="disposable runtime PG opt-in")
def test_retry_counter_ack_fencing_exhaustion_stop_and_receipt():
    outcome = run_probe(
        "transport_retry",
        [
            "service/services/chat/persistence/harness/retry.py",
            "service/services/chat/persistence/harness/state.py",
            "service/services/chat/persistence/harness/result.py",
            "service/services/chat/infrastructure/chat_worker/harness/recovery.py",
            "service/services/jobs/persistence/transitions.py",
        ],
    )
    assert outcome == {
        "cases": [
            "committed_counter_ack_loss",
            "parallel_same_attempt_once",
            "pending_fences_old_dispatch",
            "fenced_attempt_rejected",
            "counters_across_recovery",
            "exhaustion_retains_unknown",
            "stop_blocks_delivery",
            "late_receipt_without_dispatch",
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
