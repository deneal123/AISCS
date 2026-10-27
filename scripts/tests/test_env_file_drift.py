"""Наличие Compose-дефолта не оправдывает неполную синхронизацию реального env."""

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "check_sidecar_env.py"
SPEC = importlib.util.spec_from_file_location("sidecar_env_drift", SCRIPT)
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
    problems = MODULE._env_drift(example, [actual])
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
    problems = MODULE._env_drift(example, [actual])
    assert len(problems) == 1
    assert "KEY" in problems[0]
    assert "private-value" not in str(problems)


def test_absent_ignored_files_do_not_break_clean_checkout(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("KEY=\n", encoding="utf-8")
    assert MODULE._env_drift(example, [tmp_path / ".env.prod"]) == []


def test_complete_configuration_allows_deployment_specific_extras(tmp_path):
    example = tmp_path / ".env.example"
    actual = tmp_path / ".env.prod"
    example.write_text("KEY=\n", encoding="utf-8")
    actual.write_text("KEY=private-value\nEXTRA=deployment-value\n", encoding="utf-8")
    assert MODULE._env_drift(example, [actual]) == []


def test_sync_preserves_existing_values_and_does_not_rotate_secret():
    body = (
        "WORKSPACE_COORDINATION_SECRET=existing-private-secret\nMAIL__START_TLS=false\n"
    )
    example = "MAIL__START_TLS=true\nAGENTS__LLM_RETRY_BUDGET_SEC=5\n"
    updated, missing = SYNC.synchronize(body, example, provision=True)
    assert updated.startswith(body)
    assert missing == ["AGENTS__LLM_RETRY_BUDGET_SEC"]
    assert "AGENTS__LLM_RETRY_BUDGET_SEC=5\n" in updated
    assert SYNC.synchronize(updated, example, provision=True) == (updated, [])


def test_sync_provisions_unresolved_secret_once(monkeypatch):
    monkeypatch.delenv(SYNC.EXTERNAL, raising=False)
    body = "WORKSPACE_COORDINATION_SECRET=${GPTHUB_WORKSPACE_COORDINATION_SECRET:?required}\n"
    updated, missing = SYNC.synchronize(body, body, provision=True)
    secret = SYNC.entries(updated)[SYNC.COORDINATION]
    assert len(secret) >= 48 and "${" not in secret and missing == []
    assert SYNC.synchronize(updated, body, provision=True) == (updated, [])


def test_sync_fails_closed_for_unknown_settings_and_unprepared_secret(monkeypatch):
    import pytest

    monkeypatch.delenv(SYNC.EXTERNAL, raising=False)
    with pytest.raises(ValueError, match="ручная настройка"):
        SYNC.synchronize("", "PRIVATE_API_KEY=never-copy\n", provision=True)
    with pytest.raises(ValueError, match="--provision"):
        SYNC.synchronize("", "")


def test_sync_can_provision_missing_or_example_secret(monkeypatch):
    monkeypatch.delenv(SYNC.EXTERNAL, raising=False)
    example = "WORKSPACE_COORDINATION_SECRET=change-me-example\n"
    for body in ("", example):
        updated, _ = SYNC.synchronize(body, example, provision=True)
        assert len(SYNC.entries(updated)[SYNC.COORDINATION]) >= 48
        assert "change-me-example" not in updated


def test_sync_atomic_backup_is_private_and_preserves_original(tmp_path):
    import os
    import stat

    path = tmp_path / ".env.prod"
    original = "WORKSPACE_COORDINATION_SECRET=existing-private-secret\n"
    path.write_text(original, encoding="utf-8")
    SYNC.save(path, original, original + "MAIL__START_TLS=true\n")
    backups = list(tmp_path.glob(".env.prod.backup-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
    assert path.read_text(encoding="utf-8").startswith(original)
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600


def test_local_secret_is_explicit_stable_and_does_not_rotate_coordination():
    body = "WORKSPACE_COORDINATION_SECRET=existing-private-secret\n"
    example = "LOCAL_LLM_API_KEY=\nAGENTS__LOCAL_API_KEY=${LOCAL_LLM_API_KEY:-}\n"
    prepared, _ = SYNC.synchronize(body, example, provision_local=True)
    values = SYNC.entries(prepared)
    assert len(values["LOCAL_LLM_API_KEY"]) >= 48
    assert values[SYNC.COORDINATION] == "existing-private-secret"
    replay, _ = SYNC.synchronize(prepared, example, provision_local=True)
    assert replay == prepared
    untouched, _ = SYNC.synchronize(body, example)
    assert SYNC.entries(untouched)["LOCAL_LLM_API_KEY"] == ""


def test_local_secret_refuses_disagreement_or_missing_contract():
    import pytest

    body = "WORKSPACE_COORDINATION_SECRET=existing-private-secret\n"
    with pytest.raises(ValueError, match="контракте env"):
        SYNC.synchronize(body, "", provision_local=True)
    body += "LOCAL_LLM_API_KEY=" + "synthetic-local-" * 4 + "\n"
    body += "AGENTS__LOCAL_API_KEY=synthetic-other-key\n"
    with pytest.raises(ValueError, match="не согласованы"):
        SYNC.synchronize(body, "LOCAL_LLM_API_KEY=\n", provision_local=True)


def test_local_alias_is_after_its_source_when_missing_keys_are_added_alphabetically():
    body = "WORKSPACE_COORDINATION_SECRET=existing-private-secret\n"
    example = "LOCAL_LLM_API_KEY=\nAGENTS__LOCAL_API_KEY=${LOCAL_LLM_API_KEY:-}\n"
    updated, _ = SYNC.synchronize(body, example, provision_local=True)
    assert updated.index("\nLOCAL_LLM_API_KEY=") < updated.index("\nAGENTS__LOCAL_API_KEY=")
    assert SYNC.synchronize(updated, example, provision_local=True) == (updated, [])


def test_existing_forward_alias_is_reordered_without_secret_rotation_or_unrelated_changes():
    local_secret = "synthetic-local-" * 4
    body = (
        "WORKSPACE_COORDINATION_SECRET=existing-private-secret\n"
        "# Существующий порядок настроек\n"
        "AGENTS__LOCAL_API_KEY=${LOCAL_LLM_API_KEY:-}\n"
        "UNCHANGED=other-value\nLOCAL_LLM_API_KEY=" + local_secret + "\n"
    )
    example = "LOCAL_LLM_API_KEY=\nAGENTS__LOCAL_API_KEY=${LOCAL_LLM_API_KEY:-}\n"
    updated, missing = SYNC.synchronize(body, example)
    assert missing == [] and SYNC.entries(updated) == SYNC.entries(body)
    assert updated.index("\nLOCAL_LLM_API_KEY=") < updated.index("\nAGENTS__LOCAL_API_KEY=")
    assert updated.startswith(body.split("AGENTS__LOCAL_API_KEY")[0])
    assert "UNCHANGED=other-value\n" in updated


def test_compose_resolves_synchronized_local_alias_without_starting_services(tmp_path):
    import json
    import os
    import shutil
    import subprocess

    import pytest

    executable = shutil.which("docker")
    if not executable:
        pytest.skip("Для проверки dotenv нужен только Compose CLI, без запуска Docker")
    key = "synthetic-local-" * 4
    body = (
        "WORKSPACE_COORDINATION_SECRET=existing-private-secret\n"
        "AGENTS__LOCAL_API_KEY=${LOCAL_LLM_API_KEY:-}\nLOCAL_LLM_API_KEY=" + key + "\n"
    )
    example = "LOCAL_LLM_API_KEY=\nAGENTS__LOCAL_API_KEY=${LOCAL_LLM_API_KEY:-}\n"
    compose = tmp_path / "compose.yaml"
    compose.write_text(
        'name: env-alias-regression\nservices:\n  check:\n    image: busybox:latest\n'
        '    environment:\n      AGENTS__LOCAL_API_KEY: "${AGENTS__LOCAL_API_KEY:-}"\n',
        encoding="utf-8",
    )
    dotenv = tmp_path / ".env.dev"
    process_env = {
        name: value for name, value in os.environ.items()
        if name not in {"LOCAL_LLM_API_KEY", "AGENTS__LOCAL_API_KEY"}
    }

    def resolved(text):
        dotenv.write_text(text, encoding="utf-8")
        result = subprocess.run(
            [executable, "compose", "--env-file", str(dotenv), "-f", str(compose),
             "config", "--format", "json"],
            env=process_env, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        assert result.returncode == 0
        return json.loads(result.stdout)["services"]["check"]["environment"]["AGENTS__LOCAL_API_KEY"]

    assert resolved(body) == ""
    prepared, _ = SYNC.synchronize(body, example)
    assert resolved(prepared) == key
