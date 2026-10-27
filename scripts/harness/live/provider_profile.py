"""Изоляция профиля приёмки: отдельный Redis, без изменения политики dev."""

import os
import re
from urllib.parse import urlsplit


def isolate_read_change():
    from service.settings import config

    assert os.environ["HARNESS_ACCEPTANCE_SCENARIO"] in {"read_change", "question_change"}
    broker = urlsplit(os.environ["CELERY__BROKER_URL"])
    assert broker.scheme == "redis" and broker.port == 6379
    assert re.fullmatch(r"gpthub-harness-broker-[a-f0-9]{32}", broker.hostname or "")
    assert broker.username is None and broker.password is None
    selected = os.environ["HARNESS_ACCEPTANCE_PROVIDER"]
    assert selected in {"gigachat", "routerai", "openai"}
    config.agents.llm_provider = selected
    config.agents.provider_enabled = {
        name: name == selected
        for name in ("gigachat", "routerai", "openai", "openrouter", "mws", "local")
    }
    # DB 0/1 принадлежат Celery, DB 2 — политике и совместному доступу этого корпуса.
    config.redis.host = broker.hostname
    config.redis.port = 6379
    config.redis.db = 2
    config.redis.password = ""
    os.environ.update(
        REDIS__HOST=broker.hostname,
        REDIS__PORT="6379",
        REDIS__DB="2",
        REDIS__PASSWORD="",
    )
