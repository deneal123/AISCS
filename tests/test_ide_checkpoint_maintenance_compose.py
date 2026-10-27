from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("name", ["docker-compose.dev.yaml", "docker-compose.yaml"])
def test_maintenance_local_storage_ack_requires_the_same_backing_volume_as_backend(name):
    path = Path(__file__).resolve().parents[2] / "docker" / name
    if not path.exists():
        pytest.skip("Compose acceptance belongs to the superproject")
    services = yaml.safe_load(path.read_text("utf-8"))["services"]
    worker = services["celery-worker-maintenance"]
    mount = "../infra/storage:/var/lib/app/storage"
    assert mount in services["backend"]["volumes"]
    assert mount in worker["volumes"]
    assert worker["environment"]["IDE_CHECKPOINTS__MAINTENANCE_LOCAL_STORAGE_SHARED"] == "true"
    if name == "docker-compose.yaml":
        assert "IDE_CHECKPOINTS__ENABLED" not in worker["environment"]
