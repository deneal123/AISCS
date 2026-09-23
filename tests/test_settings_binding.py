"""Переменные окружения РЕАЛЬНО доезжают до конфига сайдкара.

Почему этот файл появился отдельно от остальных настроечных тестов: проверялось,
что поля СУЩЕСТВУЮТ и что дефолты совпадают, но ни один тест не проверял, что
`REDIS__HOST=redis` вообще попадает в `config.redis.host`. Оно и не попадало —
корневой `Config` был объявлен без `model_config`, то есть без
`env_nested_delimiter="__"`, а у `RedisConfig` нет `env_prefix`. Весь блок
`REDIS__*` из compose молча отбрасывался.

Хуже отбрасывания: без префикса поля `RedisConfig` привязывались к ГОЛЫМ именам,
а `PORT` в блоке `agents:` — это порт uvicorn (8090). То есть `config.redis.port`
принимал значение собственного HTTP-порта сайдкара, и включённый Redis пошёл бы
сам в себя.

Из-за этого молчали три вещи сразу: кэш сжатия контекста (каждое сжатие заново
гоняло map-reduce по ЛЛМ — это деньги), состояние circuit breaker и
provider_policy между рестартами.
"""

from __future__ import annotations

import pytest


def _fresh_config(monkeypatch: pytest.MonkeyPatch):
    """Собрать конфиг ЗАНОВО под текущим окружением.

    Модульный синглтон `config` создаётся на импорте и помнит окружение того
    момента; для проверки привязки нужен свежий экземпляр.
    """
    from service.settings import Config

    return Config()


# Ровно то, что кладёт в контейнер `docker/docker-compose.yaml` (блок `agents:`):
# PORT — для uvicorn, REDIS__* — для кэша и брейкера.
_COMPOSE_ENV = {
    "PORT": "8090",
    "REDIS__ENABLED": "true",
    "REDIS__HOST": "redis",
    "REDIS__PORT": "6379",
    "REDIS__DB": "1",
    "REDIS__PASSWORD": "s3cret",
}


@pytest.fixture()
def compose_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _COMPOSE_ENV.items():
        monkeypatch.setenv(key, value)


def test_redis_env_reaches_config(compose_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """`REDIS__*` из compose доезжают до `config.redis`."""
    cfg = _fresh_config(monkeypatch)

    assert cfg.redis.enabled is True, "REDIS__ENABLED не доехал — Redis останется выключен"
    assert cfg.redis.host == "redis"
    assert cfg.redis.port == 6379
    assert cfg.redis.db == 1, "REDIS__DB не доехал — сайдкар сядет в базу backend'а"


def test_redis_port_is_not_the_sidecar_http_port(
    compose_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`PORT` (uvicorn) НЕ должен подменять `redis.port`.

    Отдельным тестом, потому что это другой отказ: не «настройка потерялась», а
    «настройка взялась не оттуда». Совпадение с 8090 означает, что поля Redis
    привязаны к голым именам переменных.
    """
    cfg = _fresh_config(monkeypatch)

    assert cfg.redis.port != 8090, "redis.port подхватил HTTP-порт сайдкара — Redis пойдёт в себя"
    assert f":{cfg.redis.port}/" in cfg.redis.dsn


def test_agents_env_still_reaches_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """`AGENTS__*` продолжают работать — правка Redis не должна их задеть.

    Секция `agents` доступна двумя путями (свой `env_prefix` и вложенный ключ
    корня), и менять корень вслепую — как раз способ сломать второй.
    """
    monkeypatch.setenv("AGENTS__MAX_TURNS", "17")
    monkeypatch.setenv("AGENTS__RUN_TIMEOUT_SEC", "42.5")

    cfg = _fresh_config(monkeypatch)

    assert cfg.agents.max_turns == 17
    assert cfg.agents.run_timeout_sec == 42.5


def test_config_builds_without_any_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустое окружение — не ошибка: дефолты в коде остаются полом.

    Сайдкар обязан подниматься без env и без settings.toml, иначе тесты и голый
    `docker run` перестают быть возможны.
    """
    for key in (*_COMPOSE_ENV, "AGENTS__MAX_TURNS", "AGENTS__RUN_TIMEOUT_SEC"):
        monkeypatch.delenv(key, raising=False)

    cfg = _fresh_config(monkeypatch)

    assert cfg.redis.enabled is False
    assert cfg.agents.llm_provider == "auto"
