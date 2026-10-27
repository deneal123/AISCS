"""Storage policy rejects accidental booleans, unbounded values and empty budgets."""

from dataclasses import replace

import pytest

from service.services.chat.domain.ide.checkpoints.budget import CheckpointStorageBudget


@pytest.mark.parametrize(
    "changes",
    [
        {"max_user_bytes": True},
        {"max_checkpoint_bytes": True},
        {"max_pending_per_repository": True},
        {"max_user_bytes": 0},
        {"max_checkpoint_bytes": 0},
        {"max_checkpoint_bytes": 1001},
        {"max_user_bytes": 2**63},
        {"max_pending_per_repository": 0},
        {"max_pending_per_repository": 33},
        {"max_user_bytes": "1000"},
    ],
)
def test_invalid_storage_budgets_fail_closed(changes):
    with pytest.raises(ValueError, match="invalid_checkpoint_storage_budget"):
        replace(CheckpointStorageBudget(1000, 100, 4), **changes)


def test_storage_budget_keeps_user_and_single_object_limits_separate():
    limits = CheckpointStorageBudget(1000, 100, 4)
    assert limits.max_checkpoint_bytes == 100
    assert limits.max_user_bytes == 1000
