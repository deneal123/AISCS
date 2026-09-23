"""Общая обвязка тестов сайдкара.

Доменная часть conftest'а backend'а: изоляция от circuit breaker'а. Без неё тесты
«падают только в полном прогоне» — провайдер, погашенный одним тестом, выпадал из
ротации в другом.

Что СЮДА НЕ ПЕРЕЕХАЛО и почему: у backend та же автофикстура чистит ещё и
``service.shared.security.rate_limiter`` — модуль, которого в сайдкаре нет и быть не
должно (ограничение запросов пользователей — забота API, а не движка). Слепой перенос
conftest'а уронил бы весь прогон на импорте.
"""

from __future__ import annotations

import pytest

from service.domain.run_context import PrivateRunResources, use_run_execution


@pytest.fixture(autouse=True)
def _scoped_test_run_execution():
    """Give historical direct unit callers one isolated, fully scoped run.

    Production entrypoints create this scope themselves. Tests that exercise the context
    lifecycle may safely nest their own scope; ContextVar restoration keeps both owners
    isolated.
    """

    with use_run_execution(PrivateRunResources()):
        yield


@pytest.fixture(autouse=True)
def _reset_process_wide_snapshots():
    """Сбросить ПРОЦЕСС-ГЛОБАЛЬНЫЕ снимки политики и админ-настроек между тестами.

    Их глобальность — не случайность, а замысел: снимок из ``/run`` запоминается на
    процесс, чтобы им пользовались пути без своего (``/v1`` зовут по OpenAI-протоколу,
    места под политику там нет). Но в тестах это протекает: прогон ``/run`` с
    ``provider_policy={"disabled": ["mws"]}`` оставлял mws выключенным для СОСЕДНИХ
    тестов, и ``build_provider_order("mws")`` возвращал пусто — «падает только в полном
    прогоне». Ровно так это и всплыло при переезде тестов в сайдкар.
    """
    from service.shared import agent_settings as rs
    from service.shared import provider_policy_context as ppc

    def _clear() -> None:
        ppc._LAST_SEEN = None
        rs._LAST_SEEN = None

    _clear()
    yield
    _clear()


@pytest.fixture(autouse=True)
def _reset_circuit_breaker_state():
    """Чистим breaker до и после каждого теста — и in-memory, и Redis-метки.

    Breaker пишет ``provider:down:*`` с TTL 90с; между тестами они переживают, и
    погашенный провайдер молча меняет выбор в соседнем тесте.
    """
    from service.domain.client.resilience import circuit_breaker as cb

    def _clear() -> None:
        cb._DOWN_UNTIL.clear()
        try:
            r = cb._get_redis()
            if r is not None:
                keys = r.keys("provider:down:*")
                if keys:
                    r.delete(*keys)
        except Exception:  # noqa: BLE001 — Redis у сайдкара может быть выключен вовсе
            pass

    _clear()
    yield
    _clear()
