import importlib

import pytest

module = importlib.import_module("service.infrastructure.messaging.celery_app")


@pytest.mark.parametrize(
    "url",
    [
        "redis://:sensitive-value@redis:6379/0",
        "amqp://user:sensitive-value@rabbitmq:5672//",
        "redis://user:sensitive-value@redis:6379/1",
    ],
)
def test_broker_credentials_are_redacted_including_password_only_redis(url):
    redacted = module._redact_url_credentials(url)
    assert "sensitive-value" not in redacted
    assert "***:***@" in redacted


def test_separate_recovery_queue_and_profile_preserves_original_schedules(monkeypatch):
    with monkeypatch.context() as scoped:
        scoped.setenv("SERVICE__APPLICATION_PROFILE", "simulation")
        importlib.reload(module)
        routes = module.celery_app.conf.task_routes
        assert routes["service.services.simulations.tasks.execute_run"]["queue"] == "simulation"
        assert routes["service.services.simulations.tasks.recover_runs"]["queue"] == "maintenance"
        schedule = module.celery_app.conf.beat_schedule
        assert schedule["recover-simulation-runs"]["options"]["queue"] == "maintenance"
        assert any(entry["task"].endswith("cleanup_old_streams") for entry in schedule.values())
        assert not any("payment" in entry["task"] for entry in schedule.values())
    with monkeypatch.context() as scoped:
        scoped.setenv("SERVICE__APPLICATION_PROFILE", "gpthub")
        importlib.reload(module)
        assert "reconcile-pending-payments" in module.celery_app.conf.beat_schedule
        assert "recover-simulation-runs" not in module.celery_app.conf.beat_schedule
    importlib.reload(module)
