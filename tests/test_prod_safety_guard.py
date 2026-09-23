"""Стартовый fail-closed guard (main._assert_prod_safety).

dev-режим на боевом домене и dev-секрет в проде должны РОНЯТЬ старт приложения,
а не тихо поднимать анонимный WS-токен / dev test-token / insecure-cookie /
debug-роутер на публичном домене.
"""

from types import SimpleNamespace

import pytest

from service.main import _assert_prod_safety, _domain_is_local


def _cfg(
    auth_mode="prod",
    app_domain="",
    secret="x" * 32,
    dev_mode=False,
    gateway_enabled=False,
    gateway_key="",
):
    return SimpleNamespace(
        auth=SimpleNamespace(auth_mode=auth_mode, secret=secret, dev_mode=dev_mode),
        service=SimpleNamespace(app_domain=app_domain),
        agents=SimpleNamespace(
            llm_gateway_enabled=gateway_enabled, llm_gateway_api_key=gateway_key
        ),
    )


def test_open_gateway_in_prod_fails() -> None:
    """Шлюз включён с пустым ключом при auth_mode=prod → открытый /v1: старт падает."""
    with pytest.raises(RuntimeError, match="LLM_GATEWAY"):
        _assert_prod_safety(
            _cfg(
                auth_mode="prod",
                app_domain="gpthub.incellcorp.ru",
                gateway_enabled=True,
                gateway_key="",
            )
        )


def test_gateway_with_key_in_prod_ok() -> None:
    _assert_prod_safety(
        _cfg(
            auth_mode="prod",
            app_domain="gpthub.incellcorp.ru",
            gateway_enabled=True,
            gateway_key="s" * 20,
        )
    )


def test_open_gateway_allowed_in_dev() -> None:
    # Пустой ключ шлюза в dev — внутренний режим docker-сети, не роняем.
    _assert_prod_safety(
        _cfg(auth_mode="dev", app_domain="localhost", gateway_enabled=True, gateway_key="")
    )


def test_dev_mode_flag_diverging_from_prod_auth_mode_fails() -> None:
    """AUTH__DEV_MODE=true при auth_mode=prod → insecure-cookie в проде: старт падает."""
    with pytest.raises(RuntimeError, match="DEV_MODE"):
        _assert_prod_safety(
            _cfg(auth_mode="prod", app_domain="gpthub.incellcorp.ru", dev_mode=True)
        )


def test_prod_mode_without_dev_flag_ok() -> None:
    _assert_prod_safety(_cfg(auth_mode="prod", app_domain="gpthub.incellcorp.ru", dev_mode=False))


def test_dev_mode_on_local_domain_is_allowed() -> None:
    # Обычная разработка на localhost / пустом / *.local — не роняем.
    _assert_prod_safety(_cfg(auth_mode="dev", app_domain="localhost"))
    _assert_prod_safety(_cfg(auth_mode="dev", app_domain=""))
    _assert_prod_safety(_cfg(auth_mode="dev", app_domain="http://127.0.0.1:8000"))
    _assert_prod_safety(_cfg(auth_mode="dev", app_domain="gpthub.local"))


def test_dev_mode_on_production_domain_fails() -> None:
    with pytest.raises(RuntimeError, match="dev-режим"):
        _assert_prod_safety(_cfg(auth_mode="dev", app_domain="gpthub.incellcorp.ru"))


def test_prod_mode_on_production_domain_is_allowed() -> None:
    _assert_prod_safety(_cfg(auth_mode="prod", app_domain="gpthub.incellcorp.ru"))


def test_prod_mode_with_insecure_dev_secret_fails() -> None:
    with pytest.raises(RuntimeError, match="dev-дефолт"):
        _assert_prod_safety(
            _cfg(
                auth_mode="prod",
                app_domain="gpthub.incellcorp.ru",
                secret="dev-insecure-secret-change-me",
            )
        )


@pytest.mark.parametrize(
    "domain,expected",
    [
        ("", True),
        ("localhost", True),
        ("127.0.0.1", True),
        ("0.0.0.0", True),
        ("host.docker.internal", True),
        ("gpthub.local", True),
        ("api.test", True),
        ("svc.internal", True),
        ("http://localhost:3000", True),
        ("gpthub.incellcorp.ru", False),
        ("example.com", False),
        ("https://app.example.com/path", False),
    ],
)
def test_domain_is_local(domain, expected) -> None:
    assert _domain_is_local(domain) is expected
