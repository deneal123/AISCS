from pathlib import Path

import pytest
import yaml


def test_dev_smtp_is_isolated_from_provider_environment():
    root = Path(__file__).resolve().parents[2]
    path = root / "docker/docker-compose.dev.yaml"
    if not path.exists():
        pytest.skip("superproject owns Compose")
    services = yaml.safe_load(path.read_text(encoding="utf-8"))["services"]
    mailpit = services["mailpit"]
    assert mailpit["profiles"] == ["dev"]
    assert mailpit["image"] == "axllent/mailpit:v1.31.5"
    assert mailpit["ports"] == ["127.0.0.1:8026:8025"]
    assert mailpit["networks"] == ["internal", "mailpit-ui"]
    assert all(
        "mailpit-ui" not in service.get("networks", [])
        for name, service in services.items()
        if name != "mailpit"
    )
    assert mailpit["healthcheck"]["test"] == ["CMD", "/mailpit", "readyz"]
    for name in ("backend", "celery-worker-agents", "celery-worker-maintenance", "celery-beat"):
        environment = services[name]["environment"]
        assert environment["MAIL__ENABLED"] == "true"
        assert environment["MAIL__HOST"] == "mailpit"
        assert environment["MAIL__PORT"] == "1025"
        assert environment["MAIL__USE_TLS"] == "false"
        assert environment["MAIL__START_TLS"] == "false"
        assert environment["MAIL__LOGIN"] == environment["MAIL__PASSWORD"] == ""
        if name != "celery-beat":
            assert services[name]["depends_on"]["mailpit"]["condition"] == "service_healthy"
    production = yaml.safe_load((root / "docker/docker-compose.yaml").read_text(encoding="utf-8"))
    assert "mailpit" not in production["services"]
    assert "x-dev-mail" not in production
