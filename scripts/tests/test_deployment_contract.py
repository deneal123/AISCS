"""Regression checks for deployment selection, secret preservation and service topology."""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("aspa_sync_env", ROOT / "docker/sync_env.py")
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


def test_env_provisioning_is_idempotent_and_preserves_existing_secrets():
    body = "WORKSPACE_COORDINATION_SECRET=" + "w" * 48 + "\nGENERATOR_TOKEN=\n"
    example = body + "SERVICE__APPLICATION_PROFILE=simulation\n"
    updated, _ = SYNC.synchronize(body, example, provision=True, provision_generator=True)
    values = SYNC.entries(updated)
    assert values["WORKSPACE_COORDINATION_SECRET"] == "w" * 48
    assert len(values["GENERATOR_TOKEN"]) >= 48
    repeated, missing = SYNC.synchronize(updated, example, provision=True, provision_generator=True)
    assert repeated == updated
    assert missing == []


def test_env_unknown_missing_settings_fail_without_silent_copy():
    with pytest.raises(ValueError):
        SYNC.synchronize("", "NEW_PROVIDER_PASSWORD=unsafe\n", provision=True)
    with pytest.raises(ValueError):
        SYNC.entries("GENERATOR_TOKEN=a\nGENERATOR_TOKEN=b\n")


def topology(mode):
    if not shutil.which("docker") or not (ROOT / f"docker/.env.{mode}").is_file():
        pytest.skip("Local deployment integration requires Docker CLI and a private environment")
    env = os.environ.copy()
    # Validation-only placeholders, never saved or used by run.sh / containers.
    if mode == "prod":
        env.update(MINIO__ACCESS_KEY="validation-only", MINIO__SECRET_KEY="validation-only")
    result = subprocess.run(
        ["docker", "compose", "--env-file", f"docker/.env.{mode}", "-p", f"aspa-{mode}",
         "-f", "docker/docker-compose.simulation" + (".prod" if mode == "prod" else "") + ".yaml",
         "--profile", mode, "--profile", "celery", "config", "--format", "json"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    # Raw Compose diagnostics can include private env. Keep failure output bounded.
    assert result.returncode == 0, "Compose validation failed; inspect private local diagnostics"
    return json.loads(result.stdout)


@pytest.mark.parametrize("mode", ["dev", "prod"])
def test_platform_workers_storage_and_isolation(mode):
    config = topology(mode)
    services = config["services"]
    assert "celery-beat" in services
    assert "celery-worker-maintenance" in services
    assert "celery-worker-simulation" in services
    assert "celery-worker-agents" not in services
    assert not {"whisper", "video", "graphify", "ldr", "local-llm", "research"} & services.keys()
    worker = services["celery-worker-simulation"]
    assert "--queues=simulation" in worker["command"]
    assert "--beat" not in worker["command"]
    assert "--concurrency=1" in worker["command"]
    assert services["backend"]["command"] == ["server"]
    env = services["backend"]["environment"]
    assert env["CELERY__BROKER_URL"].startswith("redis://")
    assert env["SERVICE__APPLICATION_PROFILE"] == "simulation"
    assert services["generator"].get("ports", []) == []
    assert services["postgres"]["image"] == "postgres:17.4-alpine"
    if mode == "prod":
        assert "minio" not in services
        assert services["postgres"].get("ports", []) == []
        assert services["redis"].get("ports", []) == []
        assert env["MINIO__BUCKET"] == "aiscs"
        assert env["MINIO__SECURE"] == "true"
        assert json.loads(env["CORS__ALLOW_ORIGINS"]) == ["https://aiscs.incellcorp.ru"]
        assert env["AUTH__AUTH_MODE"] == "prod"
        assert env["AUTH__DEV_MODE"] == "false"
        assert services["frontend"]["build"]["args"]["REACT_APP_APPLICATION_PROFILE"] == "simulation"
        assert services["nginx"]["ports"][0]["host_ip"] == "127.0.0.1"
    else:
        frontend_port = services["frontend"]["ports"][0]["published"]
        assert "http://localhost:" + str(frontend_port) in json.loads(env["CORS__ALLOW_ORIGINS"])
