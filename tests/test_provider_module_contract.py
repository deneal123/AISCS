"""Контракт провайдер-модуля — записанный, а не заданный примером.

⚠️ ЗАЧЕМ. Реестр обращается к провайдерам утиным способом:
`getattr(module, "OPENAI_CLIENT", None)` — девять мест прода — плюс
`module.list_available_models()` ещё в четырёх. При этом единственным описанием
интерфейса был докстринг `registry.py:4`: «Все модули провайдеров имеют одинаковый
интерфейс (см. mws_client)». То есть контракт задавался ПРИМЕРОМ, и совпадение с ним
ничем не проверялось.

Цена такой формы — тихая деградация: новый провайдер без `rebuild_client` не сломает
ни импорт, ни тесты. Он просто не будет пересобираться после замены ключа в админке, и
симптом всплывёт как «поменял ключ, ничего не изменилось».

`assert_provider_module_contract` вынесена отдельно намеренно: её переиспользует страж
«добавление провайдера требует одного места».
"""

from __future__ import annotations

import inspect

import pytest

from service.domain.client import registry

# Имена, по которым к провайдеру обращаются снаружи. Значение `OPENAI_CLIENT` может быть
# None (провайдер без ключа) — важно наличие ИМЕНИ, а не его содержимое.
REQUIRED_ATTRS = (
    "OPENAI_CLIENT",
    "OPENAI_API_KEY",
)
REQUIRED_CALLABLES = (
    "rebuild_client",
    "clear_models_cache",
    "list_available_models",
    "create_chat_completion",
    "create_completion",
    "create_embedding",
)

# ⚠️ ОТКЛОНЕНИЙ БОЛЬШЕ НЕТ, и это результат, а не случайность.
# Здесь стояло исключение для `openai`: у него одного не было `get_openai_client`, а
# `active` обходил это hasattr-гардом с фолбэком на `openai.OPENAI_CLIENT` —
# клиент нативного OpenAI, кто бы ни был активен. Провайдер, добавленный без метода,
# молча получал бы ЧУЖОЙ клиент: чужой ключ, чужой биллинг. Фабрика даёт метод всем,
# словарь исключений пуст — и пусть таким остаётся.
OPTIONAL_CALLABLES = ("get_openai_client",)
KNOWN_MISSING_OPTIONAL: dict[str, set[str]] = {}


def assert_provider_module_contract(module, name: str) -> None:
    """Проверить, что модуль пригоден на роль провайдера. Переиспользуется стражами."""
    missing = [a for a in REQUIRED_ATTRS if not hasattr(module, a)]
    assert not missing, f"провайдер '{name}': нет обязательных имён {missing}"

    for fn in REQUIRED_CALLABLES:
        assert callable(getattr(module, fn, None)), (
            f"провайдер '{name}': '{fn}' обязан быть вызываемым"
        )

    allowed_missing = KNOWN_MISSING_OPTIONAL.get(name, set())
    for fn in OPTIONAL_CALLABLES:
        if fn in allowed_missing:
            continue
        assert callable(getattr(module, fn, None)), (
            f"провайдер '{name}': нет '{fn}' и он не заявлен как известное отклонение"
        )


_PROVIDERS = sorted(registry.PROVIDER_MODULES.items())


def test_registry_is_not_empty():
    """⚠️ Иначе параметризация ниже проверяла бы пустоту и всегда была зелёной."""
    assert len(_PROVIDERS) >= 5, f"в реестре лишь {len(_PROVIDERS)} провайдеров"


@pytest.mark.parametrize(("name", "module"), _PROVIDERS, ids=[n for n, _ in _PROVIDERS])
def test_provider_satisfies_the_contract(name, module):
    assert_provider_module_contract(module, name)


@pytest.mark.parametrize(("name", "module"), _PROVIDERS, ids=[n for n, _ in _PROVIDERS])
@pytest.mark.asyncio
async def test_provider_caches_its_model_list(name, module):
    """Кэш моделей — часть контракта: без него каждый расчёт каталога бьёт по сети.

    ⚠️ Проверяется СПОСОБНОСТЬ, а не имя поля. Здесь стояло `hasattr(module,
    "_MODEL_CACHE")` — и это ловило деталь реализации: кэш переехал в рантайм, имя
    исчезло, тест покраснел, хотя кэширование работает ровно как прежде. Читателей у
    приватного имени не было ни одного, кроме самого теста.
    """
    calls = {"n": 0}

    class _Client:
        class models:  # noqa: N801 — форма API OpenAI
            @staticmethod
            async def list():
                calls["n"] += 1
                return type("R", (), {"data": [{"id": "m-1"}]})()

    module.clear_models_cache()
    first = await module.list_available_models(client=_Client())
    second = await module.list_available_models(client=_Client())

    assert first == second == ["m-1"]
    assert calls["n"] == 1, f"провайдер '{name}': второй вызов пошёл по сети — кэша нет"

    module.clear_models_cache()
    await module.list_available_models(client=_Client())
    assert calls["n"] == 2, f"провайдер '{name}': clear_models_cache не сбросил кэш"


@pytest.mark.parametrize("fn_name", REQUIRED_CALLABLES)
def test_signatures_agree_across_providers(fn_name):
    """⚠️ Одинаковые имена обязаны иметь одинаковые сигнатуры.

    Реестр и фасад зовут эти функции единообразно, ничего не зная о конкретном
    провайдере. Разошедшийся параметр даёт TypeError на фейловере — то есть ровно
    тогда, когда основной провайдер уже лёг и запас особенно нужен.
    """
    shapes: dict[str, list[str]] = {}
    for name, module in _PROVIDERS:
        params = list(inspect.signature(getattr(module, fn_name)).parameters)
        shapes.setdefault(",".join(params), []).append(name)

    assert len(shapes) == 1, f"сигнатуры '{fn_name}' разошлись: {shapes}"


def test_every_provider_is_reachable_by_its_own_name():
    """`get_provider_module(name)` возвращает именно того, кто числится под этим именем."""
    for name, module in _PROVIDERS:
        assert registry.get_provider_module(name) is module, f"'{name}' резолвится не в себя"


def test_unknown_provider_resolves_to_nothing():
    """Обратная сторона: неизвестное имя даёт None, а не случайного соседа."""
    assert registry.get_provider_module("нет-такого") is None
    assert registry.get_provider_module("") is None
