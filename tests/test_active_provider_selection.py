"""Выбор активного провайдера: явный, авто и запасной.

⚠️ ЗАЧЕМ. Здесь были ДВЕ if/elif цепочки, перечислявшие провайдеров поимённо: одна для
явного `llm_provider`, вторая для режима `auto`. Добавляя провайдера, надо было вписать
себя в обе, и пропуск любой давал провайдера, которого нельзя выбрать, — без единой
ошибки. Рядом лежала третья копия знания: карта `{id(модуль): "имя"}`, из-за которой
забытый провайдер получал ИМЯ ЧУЖОГО (по умолчанию «mws») и значился не собой в трейсе,
биллинге и политике.

Всё это заменено перебором спек. Мутации показали, что механику выбора не проверял
никто: «игнорировать явный выбор», «перевернуть порядок авто» и «брать имя не у модуля»
оставались зелёными на полном наборе.
"""

from __future__ import annotations

import pytest

from service.domain.client import active, registry


@pytest.fixture
def clean_config(monkeypatch):
    """Все поля авто-выбора пусты: провайдер выбирается только тем, что задаст тест."""
    from service.settings import config

    for spec in registry.all_specs().values():
        for name in spec.auto_select_fields or (spec.api_key_field,):
            monkeypatch.setattr(config.agents, name, "", raising=False)
    monkeypatch.setattr(config.agents, "llm_provider", "auto")
    return monkeypatch


# --------------------------------------------------------------------------- #
# Явный выбор                                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", sorted(registry.PROVIDER_MODULES))
def test_explicit_choice_wins(clean_config, name):
    """⚠️ Явный `llm_provider` побеждает — даже если у провайдера ничего не настроено.

    Так админ может ткнуть в конкретного провайдера и увидеть ВНЯТНУЮ ошибку от него,
    а не молчаливый уход к соседу.
    """
    from service.settings import config

    clean_config.setattr(config.agents, "llm_provider", name)

    assert active._select_active_provider() is registry.PROVIDER_MODULES[name]


def test_unknown_explicit_choice_falls_through_to_auto(clean_config):
    """Неизвестное имя не роняет старт и не выбирает случайного — уходит в авто."""
    from service.settings import config

    clean_config.setattr(config.agents, "llm_provider", "нет-такого")
    clean_config.setattr(config.agents, "openrouter_api_key", "sk-x")

    assert active._select_active_provider() is registry.PROVIDER_MODULES["openrouter"]


# --------------------------------------------------------------------------- #
# Авто-выбор                                                                    #
# --------------------------------------------------------------------------- #
def test_auto_follows_the_declared_priority(clean_config):
    """Настроены двое — берётся тот, у кого приоритет меньше."""
    from service.settings import config

    clean_config.setattr(config.agents, "gigachat_authorization_key", "k")  # приоритет 50
    clean_config.setattr(config.agents, "mws_api_key", "k")  # приоритет 10

    assert active._select_active_provider() is registry.PROVIDER_MODULES["mws"]


def test_auto_skips_unconfigured(clean_config):
    """Пустой провайдер пропускается, даже если он раньше по порядку."""
    from service.settings import config

    clean_config.setattr(config.agents, "routerai_api_key", "k")

    assert active._select_active_provider() is registry.PROVIDER_MODULES["routerai"]


def test_auto_accepts_base_url_alone_for_self_hosted(clean_config):
    """⚠️ У MWS и OpenAI база БЕЗ ключа тоже считается настройкой.

    Это self-hosted шлюзы, где ключ бывает пустым, а адрес задан. Свести правило к
    «только ключ» значило бы перестать их видеть.

    ⚠️ Проверяем на OPENAI, а не на MWS. У MWS приоритет наименьший, и он же — запасной
    выбор «когда не настроено ничего»: тест на нём проходил бы даже при сломанном
    правиле, просто по совпадению. Мутация «оставить только ключ» это и показала.
    """
    from service.settings import config

    clean_config.setattr(config.agents, "openai_base_url", "https://gw.example/v1")

    assert active._select_active_provider() is registry.PROVIDER_MODULES["openai"]


def test_nothing_configured_falls_back_to_first_by_priority(clean_config):
    """Ничего не настроено — берём первого по порядку как заглушку.

    Вызовы к нему упадут с понятной ошибкой; это лучше, чем `None` и AttributeError
    где-то далеко от причины.
    """
    first = min(registry.all_specs().items(), key=lambda kv: kv[1].auto_select_priority)[0]

    assert active._select_active_provider() is registry.PROVIDER_MODULES[first]


# --------------------------------------------------------------------------- #
# Имя провайдера                                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", sorted(registry.PROVIDER_MODULES))
def test_provider_names_itself(name):
    """⚠️ Имя берётся у САМОГО модуля и совпадает с ключом реестра.

    Раньше имя искалось по карте `id(модуль) → строка`. Провайдер, забытый в ней,
    получал чужое имя и значился не собой везде, где это имя используется.
    """
    module = registry.PROVIDER_MODULES[name]

    assert active._provider_name_of(module) == name
    assert module.SPEC.name == name, "спека и реестр разошлись в имени"


def test_client_fallback_reads_the_active_provider_not_openai(monkeypatch):
    """⚠️ Запас берёт клиента У АКТИВНОГО, а не у нативного OpenAI.

    Здесь стояло `return openai.OPENAI_CLIENT` — клиент OpenAI, кто бы ни был
    активен. Провайдер, добавленный без хелпера `get_openai_client`, молча получал бы
    ЧУЖОЙ клиент: запросы ушли бы не туда, с чужим ключом и в чужой биллинг. Сегодня
    хелпер есть у всех, поэтому путь достижим только через такой дублёр — но именно он
    и ждёт следующего провайдера.
    """
    marker = object()

    class _NoHelper:
        PROVIDER_NAME = "acme"
        OPENAI_CLIENT = marker

    monkeypatch.setattr(active, "_ACTIVE", _NoHelper)

    assert active.get_openai_client() is marker


def test_registry_key_comes_from_the_spec():
    """Ключ реестра — это `PROVIDER_NAME` модуля, а не отдельно написанная строка."""
    for name, module in registry.PROVIDER_MODULES.items():
        assert module.PROVIDER_NAME == name
