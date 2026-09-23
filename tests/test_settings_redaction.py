import pytest

from service.settings import Config, redact_config_for_logging


def test_redact_survives_missing_auth_section(monkeypatch: pytest.MonkeyPatch):
    """Секция auth НЕОБЯЗАТЕЛЬНА (`auth: AuthConfig | None = None`) — редактор обязан это пережить.

    Тест ниже присваивает `config.auth.auth_mode`, то есть работает только когда
    секция есть; conftest её подаёт, поэтому случай `None` не покрывался вовсе.
    А `redact_config_for_logging` вызывается на уровне модуля (`main.py:31`), так что
    разыменование None здесь — падение на СТАРТЕ, до первого запроса.
    """
    config = Config()
    config.auth = None

    redacted = redact_config_for_logging(config)

    assert redacted["auth"] == {"auth_mode": None}


def test_redact_config_for_logging_returns_whitelisted_fields_only():
    config = Config()
    config.service.name = "svc"
    config.service.server_port = 8080
    config.auth.auth_mode = "prod"
    config.storage.backend = "minio"
    config.auth.secret = "super-secret"
    config.pg.password = "db-secret"
    config.minio.access_key = "access-key"
    config.minio.secret_key = "secret-key"
    config.redis.password = "redis-secret"
    config.agents.openai_api_key = "openai-secret"

    redacted = redact_config_for_logging(config)

    assert redacted == {
        "service": {"name": "svc", "server_port": 8080},
        "auth": {"auth_mode": "prod"},
        "storage": {"backend": "minio"},
    }

    dump = str(redacted)
    for value in [
        "super-secret",
        "db-secret",
        "access-key",
        "secret-key",
        "redis-secret",
        "openai-secret",
    ]:
        assert value not in dump
