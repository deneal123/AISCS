"""Настоящие PostgreSQL транзакции continuation, не полный worker restart/settlement."""

import os

import pytest

from tests.harness_postgres import run_probe


@pytest.mark.skipif(os.getenv("HARNESS_RUNTIME_LIVE") != "1", reason="disposable runtime PG opt-in")
def test_model_terminal_counter_and_duplicate_receipt_use_same_journal():
    assert run_probe(
        "model_continuation",
        [
            "service/shared/harness_protocol.py",
            "service/services/chat/persistence/harness/runtime.py",
            "service/services/chat/persistence/harness/grants.py",
            "service/services/chat/persistence/harness/state.py",
        ],
    ) == {
        "cases": [
            "length_receipt_survives_repository_reload",
            "new_model_slot_after_partial",
            "counter_reset_rejected",
            "duplicate_receipt_no_spend_change",
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
