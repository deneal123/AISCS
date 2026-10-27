"""Настоящие транзакции PostgreSQL; отдельная БД, без платных вызовов и workspace."""

import os

import pytest

from tests.harness_postgres import run_probe


@pytest.mark.skipif(os.getenv("HARNESS_RUNTIME_LIVE") != "1", reason="disposable runtime PG opt-in")
def test_parallel_grants_dispatch_receipts_and_unknown_cost():
    paths = [
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
        "service/services/chat/persistence/harness/reservations.py",
        "service/services/chat/persistence/harness/result.py",
        "service/services/chat/application/harness_capability.py",
        "service/services/billing/application/frozen_pricing.py",
        "service/services/billing/domain/pricing.py",
        "service/shared/model_class.py",
    ]
    outcome = run_probe("grant_concurrency", paths)
    assert outcome == {
        "cases": [
            "parallel_grants_share_budget",
            "grant_replay_and_conflict",
            "dispatch_once",
            "receipt_replay_and_conflict",
            "cumulative_minimum_once",
            "unknown_cost_blocks_allocated_dispatch",
            "stop_keeps_unknown_cost",
            "late_receipt_after_stop",
            "local_zero_budget_no_paid_dispatch",
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
