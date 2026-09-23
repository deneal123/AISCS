"""Добавление провайдера требует ОДНОГО места — и это проверяется, а не обещается.

⚠️ ЗАЧЕМ. Раньше знание о провайдере жило в шести независимых списках: реестр, две
if/elif цепочки выбора, карта имён по `id()`, набор «понимает include_usage» и набор
«старый диалект function-calling». Пропуск любого не давал ни ошибки, ни лога — просто
провайдер молча терял точный учёт токенов, получал 422 на инструментах или значился в
трейсе под ЧУЖИМ именем.

Тест объявляет фиктивного провайдера ЦЕЛИКОМ ВНУТРИ СЕБЯ — одна спека и один модуль в
пять строк — и не правит ни строчки прода. Если завтра кто-то заведёт седьмой список,
этот тест покраснеет: dummy в него не попадёт.
"""

from __future__ import annotations

import sys
import types

import pytest

from service.domain.client import active, registry
from service.domain.client.protocol import GIGACHAT_TOOL_CAPABILITIES
from service.domain.client.providers import credentials, function_dialect
from service.domain.client.providers.runtime import ProviderRuntime, module_getattr
from service.domain.client.providers.spec import ProviderSpec
from tests.test_provider_module_contract import assert_provider_module_contract

DUMMY = ProviderSpec(
    name="dummy",
    label="Dummy",
    default_base_url="https://dummy.invalid",
    # ⚠️ Поле настроек берём СВОБОДНОЕ — то, которое не заявлено ни одной настоящей
    # спекой. Спека адресует поля по имени, а завести новое поле в `AgentsConfig` из
    # теста нельзя: там `extra="forbid"`. Возьми мы чужое (`openrouter_api_key`) —
    # заполнив его для dummy, мы заодно «настроили» бы openrouter, и авто-выбор ушёл бы
    # к нему: тест падал бы, ничего не говоря о самом свойстве.
    api_key_field="mem0_api_key",
    fallback_models=("dummy-1",),
    fallback_model_capabilities=(("dummy-1", ("chat", "tools")),),
    supports_stream_usage=True,
    tool_capabilities=GIGACHAT_TOOL_CAPABILITIES,
    auto_select_priority=999,
)


@pytest.fixture
def dummy_provider(monkeypatch):
    """Собрать провайдера так же, как это сделал бы новый файл в `providers/`."""
    module = types.ModuleType("service.domain.client.providers.dummy")
    module.SPEC = DUMMY
    module.PROVIDER_NAME = DUMMY.name

    runtime = ProviderRuntime(DUMMY)
    module.__getattr__ = module_getattr(runtime)
    module.rebuild_client = runtime.rebuild
    module.get_openai_client = lambda: runtime.client
    module.clear_models_cache = runtime.models.clear
    module.list_available_models = runtime.list_available_models
    module.create_chat_completion = lambda **kw: runtime.chat_completion(None, **kw)
    module.create_completion = lambda **kw: runtime.completion(None, **kw)
    module.create_embedding = lambda **kw: runtime.embedding(None, **kw)

    monkeypatch.setitem(sys.modules, "service.domain.client.providers.dummy", module)

    # ⚠️ Регистрируем ТАК ЖЕ, как это сделал бы новый файл в `providers/`: добавляем
    # модуль в источники и пересобираем реестр его собственным обходом. Вписать dummy
    # прямо в `PROVIDER_MODULES` было бы проще, но тогда тест проверял бы свою подмену,
    # а не то, что реестр действительно выводится из модулей.
    monkeypatch.setattr(
        registry, "_PROVIDER_SOURCES", (*registry._PROVIDER_SOURCES, module), raising=True
    )
    monkeypatch.setattr(registry, "PROVIDER_MODULES", registry._discover(), raising=True)
    return module


def test_dummy_satisfies_the_module_contract(dummy_provider):
    """Тот же контракт, что и у настоящих пяти — проверка переиспользуется."""
    assert_provider_module_contract(dummy_provider, DUMMY.name)


def test_registry_resolves_the_new_provider(dummy_provider):
    """Реестр знает его под ЕГО именем, а не под каким-то другим."""
    assert registry.get_provider_module("dummy") is dummy_provider
    assert registry.get_spec("dummy") is DUMMY
    assert "dummy" in registry.all_specs()


def test_stream_usage_follows_the_spec(dummy_provider):
    """⚠️ ДЕНЕЖНЫЙ ФЛАГ: запрашивать ли usage у провайдера в стриме.

    Раньше это был набор имён в `streaming`. Провайдер, забытый там, молча уходил на
    оценку вместо точного учёта.
    """
    from service.domain.client.calls.streaming import _supports_stream_usage

    assert _supports_stream_usage("dummy") is True
    assert _supports_stream_usage("mws") is False, "проверка потеряла разрешающую силу"


def test_function_dialect_follows_the_spec(dummy_provider):
    """Раньше — отдельное множество; забытый провайдер получал 422 на инструментах."""
    assert function_dialect.uses_legacy_functions("dummy") is True
    assert function_dialect.uses_legacy_functions("openrouter") is False


def test_explicit_choice_reaches_the_new_provider(dummy_provider, monkeypatch):
    """Явный `llm_provider=dummy` выбирает именно его."""
    from service.settings import config

    monkeypatch.setattr(config.agents, "llm_provider", "dummy")

    assert active._select_active_provider() is dummy_provider


def test_auto_choice_reaches_the_new_provider(dummy_provider, monkeypatch):
    """И авто-выбор тоже: у dummy наихудший приоритет, поэтому гасим всех остальных."""
    from service.settings import config

    monkeypatch.setattr(config.agents, "llm_provider", "auto")
    for name, spec in registry.all_specs().items():
        for field in spec.auto_select_fields or (spec.api_key_field,):
            monkeypatch.setattr(config.agents, field, "" if name != "dummy" else "sk-x")

    assert active._select_active_provider() is dummy_provider


def test_provider_name_is_taken_from_the_module(dummy_provider):
    """Имя объявляет сам модуль — карты `id() → строка` больше нет."""
    assert active._provider_name_of(dummy_provider) == "dummy"


def test_rebuild_produces_a_fresh_client(dummy_provider, monkeypatch):
    """⚠️ Замена ключа в админке доходит до нового провайдера.

    Это то самое «поменял ключ, ничего не изменилось», ради чего состояние уехало из
    модульных глобалов в рантайм.
    """
    credentials.set_override("dummy", "sk-первый")
    try:
        assert active.rebuild_provider("dummy") is True
        before = dummy_provider.OPENAI_CLIENT

        credentials.set_override("dummy", "sk-второй")
        assert active.rebuild_provider("dummy") is True

        assert dummy_provider.OPENAI_CLIENT is not before, "пересборка не дошла"
        assert dummy_provider.OPENAI_API_KEY == "sk-второй"
    finally:
        credentials.clear_override("dummy")


def test_new_provider_joins_the_failover_order(dummy_provider, monkeypatch):
    """Фейловер видит его наравне с остальными."""
    from service.shared.agent_settings import runtime_settings

    monkeypatch.setattr(
        runtime_settings,
        "get_agents",
        lambda name, default=None: (
            True
            if name == "provider_failover_enabled"
            else ("dummy" if name == "provider_fallback_order" else default)
        ),
    )
    credentials.set_override("dummy", "sk-x")
    try:
        active.rebuild_provider("dummy")
        assert "dummy" in registry.build_provider_order("mws")
    finally:
        credentials.clear_override("dummy")


# --------------------------------------------------------------------------- #
# Поля настроек: спека ссылается по имени, и имя обязано существовать            #
# --------------------------------------------------------------------------- #
def test_every_spec_field_exists_in_settings():
    """⚠️ Спека адресует поля `AgentsConfig` ПО ИМЕНИ — опечатка тут тихая.

    `settings_value` читает через `getattr(..., None)`: несуществующее имя даёт None,
    провайдер молча остаётся без ключа и выглядит «не настроенным». Ошибки нет нигде.
    """
    from service.settings import AgentsConfig

    declared = set(AgentsConfig.model_fields)
    missing: list[str] = []
    for name, spec in registry.all_specs().items():
        fields = [
            spec.api_key_field,
            *spec.api_key_fallback_fields,
            spec.base_url_field,
            *spec.base_url_fallback_fields,
            spec.timeout_field,
            spec.ttl_field,
            *(spec.auto_select_fields or ()),
        ]
        missing += [f"{name}.{f}" for f in fields if f and f not in declared]

    assert not missing, f"спеки ссылаются на несуществующие поля настроек: {missing}"


def test_every_provider_shaped_setting_is_claimed_by_a_spec():
    """⚠️ Обратная сторона: поле-сирота вида `*_api_key` без хозяина.

    Так выглядит провайдер, у которого завели настройки, но забыли спеку: переменная
    есть, админ её выставляет, и не происходит НИЧЕГО. Проверка ловит это ДО того, как
    станет вопросом поддержки.
    """
    from service.settings import AgentsConfig

    # Ключи не-провайдерских подсистем. Список явный: молчаливое исключение по маске
    # снова сделало бы проверку декоративной.
    NON_PROVIDER = {
        "memos_api_key",
        "mem0_api_key",
        "ldr_api_key",
        "llm_gateway_api_key",
        "graphify_api_key",
        "whisper_api_key",
        "opendataloader_api_key",
        "duckdb_api_key",
        # Ключ СОСЕДНЕГО СЕРВИСА, а не провайдера LLM: закрывает сайдкар песочницы.
        "workspace_api_key",
        # То же самое: закрывает сайдкар просмотра видео. ⚠️ Страж сработал ровно как
        # задуман — новый ключ вида `*_api_key` обязан быть либо заявлен спекой провайдера,
        # либо назван здесь; молча пройти он не может.
        "video_api_key",
    }

    claimed: set[str] = set()
    for spec in registry.all_specs().values():
        claimed |= {
            f
            for f in (
                spec.api_key_field,
                *spec.api_key_fallback_fields,
                spec.base_url_field,
                *spec.base_url_fallback_fields,
            )
            if f
        }

    orphans = sorted(
        name
        for name in AgentsConfig.model_fields
        if name.endswith("_api_key") and name not in claimed and name not in NON_PROVIDER
    )

    assert not orphans, (
        f"поля настроек без спеки: {orphans}. Либо у провайдера нет декларации, либо "
        f"поле принадлежит другой подсистеме — тогда впишите его в NON_PROVIDER."
    )
