import pytest
from pydantic import ValidationError

from service.shared.ide_checkpoint_settings import IdeCheckpointConfig


def test_snapshot_rollout_is_disabled_until_migration_and_runtime_are_ready():
    options = IdeCheckpointConfig()
    assert not options.enabled
    assert options.max_snapshot_bytes <= options.max_user_bytes
    assert options.max_pending_per_repository == 4


def test_snapshot_rollout_uses_the_existing_nested_environment_owner(monkeypatch):
    from service.settings import Config

    monkeypatch.setenv("IDE_CHECKPOINTS__ENABLED", "true")
    monkeypatch.setenv("IDE_CHECKPOINTS__MAX_USER_BYTES", "2147483648")
    options = Config(_env_file=None).ide_checkpoints
    assert options.enabled and options.max_user_bytes == 2147483648


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_user_bytes": 1},
        {"max_file_bytes": 2**31},
        {"max_total_bytes": 1},
        {"max_snapshot_bytes": 1},
        {"entries": 65534},
        {"depth": 65},
        {"max_pending_per_repository": 0},
    ],
)
def test_inconsistent_snapshot_capacity_is_a_startup_error(overrides):
    with pytest.raises(ValidationError):
        IdeCheckpointConfig(**overrides)
