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
    example = "GENERATOR_TOKEN=\nSERVICE__APPLICATION_PROFILE=simulation\n"
    body = "GENERATOR_TOKEN=\nSERVICE__APPLICATION_PROFILE=simulation\n"
    updated, missing = SYNC.synchronize(body, example, provision_generator=True)
    values = SYNC.entries(updated)
    assert len(values["GENERATOR_TOKEN"]) >= 48
    assert values["SERVICE__APPLICATION_PROFILE"] == "simulation"
    assert missing == []
    repeated, _ = SYNC.synchronize(updated, example, provision_generator=True)
    assert repeated == updated


def test_env_unknown_missing_settings_fail_without_silent_copy():
    with pytest.raises(ValueError):
        SYNC.synchronize("", "NEW_PROVIDER_PASSWORD=unsafe\n")
    with pytest.raises(ValueError):
        SYNC.entries("GENERATOR_TOKEN=a\nGENERATOR_TOKEN=b\n")


def topology(mode):
    if not shutil.which("docker") or not (ROOT / f"docker/.env.{mode}").is_file():
        pytest.skip("Local deployment integration requires Docker CLI and a private environment")
    env = os.environ.copy()
    # Validation-only placeholders, never saved or used by run.sh / containers.
    if mode == "prod":
        env.update(MINIO__ACCESS_KEY="validation-only", MINIO__SECRET_KEY="validation-only")
    compose = "docker/docker-compose.yaml" if mode == "prod" else "docker/docker-compose.dev.yaml"
    result = subprocess.run(
        ["docker", "compose", "--env-file", f"docker/.env.{mode}", "-p", f"aspa-{mode}",
         "-f", compose, "--profile", mode, "--profile", "celery", "config", "--format", "json"],
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
    removed = {"whisper", "video", "graphify", "ldr", "local-llm", "research",
               "workspace", "agents", "duckdb", "opendataloader", "memos", "searxng", "qdrant"}
    assert not removed & services.keys()
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
    assert services["frontend"]["build"]["args"]["REACT_APP_APPLICATION_PROFILE"] == "simulation"
    if mode == "prod":
        assert "minio" not in services
        assert services["postgres"].get("ports", []) == []
        assert services["redis"].get("ports", []) == []
        assert env["MINIO__BUCKET"] == "aiscs"
        assert env["MINIO__SECURE"] == "true"
        assert json.loads(env["CORS__ALLOW_ORIGINS"]) == ["https://aiscs.incellcorp.ru"]
        assert env["AUTH__AUTH_MODE"] == "prod"
        assert env["AUTH__DEV_MODE"] == "false"
        assert services["nginx"]["ports"][0]["host_ip"] == "127.0.0.1"
    else:
        frontend_port = services["frontend"]["ports"][0]["published"]
        assert "http://localhost:" + str(frontend_port) in json.loads(env["CORS__ALLOW_ORIGINS"])


@pytest.mark.parametrize("mode", ["dev", "prod"])
def test_generator_runs_on_gpu_with_geometry_cache(mode):
    config = topology(mode)
    generator = config["services"]["generator"]
    assert generator["build"]["target"] == "gpu-runtime"
    assert generator["gpus"], "генератор обязан видеть GPU"
    env = generator["environment"]
    assert env["GENERATOR_FIELD_BACKEND"] == "gpu"
    assert env["GENERATOR_GEOMETRY_CACHE_DIR"] == "/geometry-cache"
    assert len(env["GENERATOR_GEOMETRY_CACHE_MANIFEST_SHA256"]) == 64
    mounts = {volume["target"]: volume for volume in generator["volumes"]}
    assert mounts["/geometry-cache"]["read_only"] is True
    assert mounts["/morphology-index"]["read_only"] is True
