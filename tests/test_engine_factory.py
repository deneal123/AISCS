"""Выбор движка: сайдкар — единственная точка исполнения.

Раньше здесь проверялась развилка in-process / http и канареечный список: это была
страховка на время миграции. Домен физически уехал в сайдкар, backend его исполнить не
может, и развилки не осталось — остался лишь ЗАПРЕТ на прежний режим.

Канарейка проверяется тем же предикатом ``uses_http_engine``: по нему воркер решает,
класть ли в тело презайнед-ссылки на файлы.
"""

from types import SimpleNamespace

import pytest

from service.infrastructure.agents_client.engine_factory import (
    select_agent_engine,
    uses_http_engine,
)


def _cfg(mode: str = "http"):
    return SimpleNamespace(
        agents=SimpleNamespace(
            engine_mode=mode,
            engine_canary_user_ids="",
            sidecar_url="http://agents:8090",
            sidecar_timeout_sec=600.0,
        )
    )


def test_returns_http_engine() -> None:
    assert type(select_agent_engine(_cfg(), user_id="7")).__name__ == "HttpAgentEngine"


def test_inprocess_is_refused_loudly() -> None:
    """Заглушка-фолбэк здесь была бы опаснее отказа: она выглядела бы как рабочая
    деградация, а на деле упала бы импортом отсутствующего домена."""
    with pytest.raises(RuntimeError, match="inprocess"):
        select_agent_engine(_cfg(mode="inprocess"), user_id="7")


def test_predicate_still_drives_file_links() -> None:
    """По этому же предикату воркер решает, класть ли презайнед-ссылки (Фаза 0b.4).
    Разъедется с фабрикой — у пользователя молча отвалится аналитика файлов."""
    assert uses_http_engine(_cfg()) is True


def test_default_mode_is_the_one_that_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """Дефолт БЕЗ переменной окружения обязан быть рабочим режимом.

    Тесты выше используют подставной конфиг, поэтому проверяли поведение ПРИ
    заданном режиме и ни разу — какой режим получится, если не задать ничего.
    В эту щель и провалилось: дефолт остался `inprocess` с тех пор, когда он был
    рабочим, а `.env.prod` ключа не содержит. То есть прод поднимался в режиме,
    который фабрика отвергает, — падение на первом же сообщении.
    """
    monkeypatch.delenv("AGENTS__ENGINE_MODE", raising=False)

    from service.settings import AgentsConfig

    assert AgentsConfig().engine_mode == "http"


def test_default_config_selects_a_real_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сквозная проверка: конфиг по умолчанию → фабрика отдаёт движок, а не исключение."""
    monkeypatch.delenv("AGENTS__ENGINE_MODE", raising=False)

    from service.settings import Config

    assert type(select_agent_engine(Config(), user_id="7")).__name__ == "HttpAgentEngine"
