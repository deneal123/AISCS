"""Корпус использует свой Redis; главная политика провайдеров не изменяется."""

import pytest

from scripts.harness.live.provider_profile import isolate_read_change
from service.settings import config


@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai"])
@pytest.mark.parametrize("scenario", ["read_change", "question_change"])
def test_owned_provider_profile_uses_disposable_broker_database(monkeypatch, provider, scenario):
    original_redis = config.redis
    original_agents = config.agents
    monkeypatch.setattr(config, "redis", original_redis.model_copy(deep=True))
    monkeypatch.setattr(config, "agents", original_agents.model_copy(deep=True))
    monkeypatch.setenv("HARNESS_ACCEPTANCE_SCENARIO", scenario)
    monkeypatch.setenv("HARNESS_ACCEPTANCE_PROVIDER", provider)
    host = "gpthub-harness-broker-" + "a" * 32
    monkeypatch.setenv("CELERY__BROKER_URL", f"redis://{host}:6379/0")
    for key in ("REDIS__HOST", "REDIS__PORT", "REDIS__DB", "REDIS__PASSWORD"):
        monkeypatch.setenv(key, "original")
    isolate_read_change()
    assert config.redis.dsn == f"redis://{host}:6379/2"
    assert config.agents.llm_provider == provider
    assert [key for key, enabled in config.agents.provider_enabled.items() if enabled] == [provider]
    assert config.redis is not original_redis and config.agents is not original_agents


@pytest.mark.parametrize(
    "broker",
    ["redis://redis:6379/0", "redis://gpthub-harness-broker-" + "a" * 32 + ":6380/0"],
)
def test_unowned_broker_is_rejected_before_config_mutation(monkeypatch, broker):
    original = config.redis.model_dump()
    monkeypatch.setenv("HARNESS_ACCEPTANCE_SCENARIO", "read_change")
    monkeypatch.setenv("CELERY__BROKER_URL", broker)
    with pytest.raises(AssertionError):
        isolate_read_change()
    assert config.redis.model_dump() == original
