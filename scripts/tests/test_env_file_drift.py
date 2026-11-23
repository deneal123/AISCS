"""Наличие Compose-дефолта не оправдывает неполную синхронизацию реального env."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check_env_contract.py"
SPEC = importlib.util.spec_from_file_location("env_contract_drift", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SYNC_SPEC = importlib.util.spec_from_file_location(
    "sync_env", SCRIPT.parents[1] / "docker" / "sync_env.py"
)
SYNC = importlib.util.module_from_spec(SYNC_SPEC)
SYNC_SPEC.loader.exec_module(SYNC)


def test_all_keys_checked_including_backend_and_defaulted_fields(tmp_path):
    example = tmp_path / ".env.example"
    actual = tmp_path / ".env.prod"
    example.write_text(
        "HARNESS__IDE_ENABLED=true\nMAIL__START_TLS=true\n", encoding="utf-8"
    )
    actual.write_text(
        "HARNESS__IDE_ENABLED=true\nPRIVATE_TOKEN=never-print-this\n", encoding="utf-8"
    )
    problems = MODULE.env_drift(example, [actual])
    assert len(problems) == 1
    assert "MAIL__START_TLS" in problems[0]
    assert "never-print-this" not in str(problems)


def test_duplicate_assignments_rejected_without_values(tmp_path):
    example = tmp_path / ".env.example"
    actual = tmp_path / ".env.dev"
    example.write_text("KEY=\n", encoding="utf-8")
    actual.write_text(
        "KEY=first-private-value\nKEY=second-private-value\n", encoding="utf-8"
    )
    problems = MODULE.env_drift(example, [actual])
    assert len(problems) == 1
    assert "KEY" in problems[0]
    assert "private-value" not in str(problems)


def test_absent_ignored_files_do_not_break_clean_checkout(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("KEY=\n", encoding="utf-8")
    assert MODULE.env_drift(example, [tmp_path / ".env.prod"]) == []


def test_complete_configuration_allows_deployment_specific_extras(tmp_path):
    example = tmp_path / ".env.example"
    actual = tmp_path / ".env.prod"
    example.write_text("KEY=\n", encoding="utf-8")
    actual.write_text("KEY=private-value\nEXTRA=deployment-value\n", encoding="utf-8")
    assert MODULE.env_drift(example, [actual]) == []


def test_repository_example_covers_both_configurations():
    root = SCRIPT.parents[1]
    example = root / "docker/.env.example"
    paths = [root / "docker/.env.dev", root / "docker/.env.prod"]
    assert MODULE.env_drift(example, paths) == []


def test_sync_refuses_to_copy_unknown_settings():
    # Молчаливое копирование значения из шаблона — это подстановка чужого
    # секрета; неизвестные ключи должны останавливать синхронизацию.
    with pytest.raises(ValueError, match="ручная настройка"):
        SYNC.synchronize("", "PRIVATE_API_KEY=never-copy\n")


def test_sync_preserves_complete_body_untouched():
    body = "MAIL__START_TLS=false\nGENERATOR_TOKEN=existing-value\n"
    updated, missing = SYNC.synchronize(body, "MAIL__START_TLS=true\nGENERATOR_TOKEN=\n")
    assert updated == body
    assert missing == []


def test_sync_provisions_only_the_generator_token_once():
    body = "MAIL__START_TLS=false\nGENERATOR_TOKEN=\n"
    example = body
    updated, _ = SYNC.synchronize(body, example, provision_generator=True)
    token = SYNC.entries(updated)["GENERATOR_TOKEN"]
    assert len(token) >= 48 and "${" not in token
    repeated, _ = SYNC.synchronize(updated, example, provision_generator=True)
    assert repeated == updated


def test_sync_rejects_corrupted_generator_token():
    body = "MAIL__START_TLS=false\nGENERATOR_TOKEN=short\n"
    with pytest.raises(ValueError, match="unsupported generator credential"):
        SYNC.synchronize(body, body, provision_generator=True)


def test_sync_duplicate_keys_fail_without_values():
    with pytest.raises(ValueError, match="повтор ключа"):
        SYNC.entries("GENERATOR_TOKEN=a\nGENERATOR_TOKEN=b\n")


def test_sync_atomic_backup_is_private_and_preserves_original(tmp_path):
    import os
    import stat

    path = tmp_path / ".env.prod"
    original = "MAIL__START_TLS=false\n"
    path.write_text(original, encoding="utf-8")
    SYNC.save(path, original, original + "GENERATOR_TOKEN=value\n")
    backups = list(tmp_path.glob(".env.prod.backup-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
    assert path.read_text(encoding="utf-8").startswith(original)
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
