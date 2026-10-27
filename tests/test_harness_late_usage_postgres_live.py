"""Поздний usage и Stop/TTL на одноразовой PostgreSQL-БД, без платных вызовов."""

import os

import pytest

from tests.harness_postgres import run_probe


@pytest.mark.skipif(os.getenv("HARNESS_RUNTIME_LIVE") != "1", reason="disposable runtime PG opt-in")
def test_late_exact_usage_reconciles_unknown_without_new_dispatch():
    result = run_probe(
        "late_usage",
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
            "service/services/billing/persistence/sql.py",
        ],
    )
    assert result == {
        "cases": [
            "unknown_hold_survives_stop_ttl",
            "exact_usage_resolves_same_operation",
            "concurrent_receipts_count_once",
            "late_usage_cannot_revive_execution",
            "changed_receipt_rejected",
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
