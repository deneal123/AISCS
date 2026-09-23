"""Провайдер собирается ПРИ ИМПОРТЕ, без единого исключения.

⚠️ НАЙДЕНО ЖИВЫМ ЗАПУСКОМ, А НЕ ТЕСТАМИ. Поднял dev-стек — и первой же строкой в логах
сайдкара: `Failed to initialize GigaChat client`, `NameError: name '_RUNTIME' is not
defined`. GigaChat не инициализировался НИКОГДА с самого перехода на фабрику провайдеров.

Механизм — обратный вызов во время конструирования:

    ProviderRuntime.__init__ → _build → create_client → make_http_client
    → хук провайдера _make_http_client → _get_token_manager
    → _resolve_authorization_key → _RUNTIME

`_RUNTIME` в этот момент ПРИСВАИВАЕТСЯ: правая часть ещё вычисляется, имени в модуле
нет. Хук не может зависеть от рантайма, который его же и конструирует.

## Почему 1037 тестов молчали

Все они зовут хуки ПОСЛЕ импорта модуля, когда `_RUNTIME` уже существует. А `_build`
ловит исключение и оставляет клиент `None` — сервис поднимается, отвечает на `/health`,
и единственный след это одна строка в логах старта среди прочего шума.

Отсюда форма стража: он импортирует модуль ЗАНОВО в чистом состоянии и ловит то, что
прод глушит, — сам факт исключения при сборке.
"""

from __future__ import annotations

import importlib
import logging

import pytest

from service.domain.client import registry

_PROVIDERS = sorted(registry.PROVIDER_MODULES)


def test_there_are_providers_to_check():
    """Контроль предпосылки: пустой реестр сделал бы проверки ниже пустыми."""
    assert len(_PROVIDERS) >= 4


@pytest.mark.parametrize("name", _PROVIDERS)
def test_provider_module_builds_without_errors(name, caplog):
    """Импорт провайдера не должен ронять исключений — даже проглоченных.

    ⚠️ Смотрим на ЛОГИ, а не на результат импорта. `_build` ловит всё подряд («провайдер
    без клиента не должен ронять импорт») и оставляет `client=None` — то есть при
    сломанном провайдере импорт формально успешен. Ровно так поломка и прожила.
    """
    module = registry.PROVIDER_MODULES[name]

    with caplog.at_level(logging.ERROR):
        importlib.reload(module)

    failures = [
        r
        for r in caplog.records
        if r.exc_info is not None and "Failed to" in r.message and "client" in r.message
    ]
    assert not failures, (
        f"провайдер '{name}' не собрался при импорте: {failures[0].message}. "
        "Наружу это выглядит как «провайдер просто не работает»: сервис поднимается, "
        "клиент остаётся None, в логах одна строка при старте."
    )


@pytest.mark.parametrize("name", _PROVIDERS)
def test_provider_hooks_do_not_call_back_into_runtime(name):
    """⚠️ Структурный запрет на ту же ошибку в любом другом провайдере.

    Хуки перечислены в `ProviderHooks` и вызываются ИЗ конструктора рантайма. Любое
    обращение хука к `_RUNTIME` — это обращение к имени, которого в тот момент ещё нет.
    Проверяем не поведение, а форму: так ловится и провайдер, у которого хук пока не
    исполняется на нашем пути.
    """
    import ast
    import inspect

    module = registry.PROVIDER_MODULES[name]
    try:
        source = inspect.getsource(module)
    except OSError:  # pragma: no cover — модуль без исходника
        pytest.skip("исходник недоступен")

    tree = ast.parse(source)
    # Имена функций, переданных в ProviderHooks(...) этого модуля.
    hook_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "ProviderHooks"):
            continue
        for kw in node.keywords:
            if isinstance(kw.value, ast.Name):
                hook_names.add(kw.value.id)

    if not hook_names:
        pytest.skip("у провайдера нет хуков")

    # Что вызывает каждая функция модуля — чтобы поймать и косвенное обращение
    # (хук → вспомогательная функция → _RUNTIME), а именно так и было у GigaChat.
    calls: dict[str, set[str]] = {}
    uses_runtime: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        called: set[str] = set()
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                called.add(inner.func.id)
            if isinstance(inner, ast.Name) and inner.id == "_RUNTIME":
                uses_runtime.add(node.name)
        calls[node.name] = called

    def _reaches_runtime(fn: str, seen: set[str]) -> bool:
        if fn in uses_runtime:
            return True
        if fn in seen:
            return False
        seen.add(fn)
        return any(_reaches_runtime(nxt, seen) for nxt in calls.get(fn, ()) if nxt in calls)

    offenders = [h for h in sorted(hook_names) if _reaches_runtime(h, set())]
    assert not offenders, (
        f"провайдер '{name}': хук(и) {offenders} обращаются к _RUNTIME. Хуки вызываются "
        "ИЗ конструктора рантайма, когда имя ещё не присвоено — будет NameError, а "
        "провайдер молча останется без клиента."
    )
