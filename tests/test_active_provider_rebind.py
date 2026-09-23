"""Пересборка провайдера после смены ключа доходит до ВСЕХ модулей клиентского слоя.

⚠️ ЗАЧЕМ ЭТОТ ФАЙЛ ПОЯВИЛСЯ. Клиентский слой был одним модулем на 680 строк, и
`ACTIVE_PROVIDER` читался внутри него как обычная глобальная переменная. После разделения
на `active` / `catalog` / `chat` / `streaming` у этого имени появился ровно один
безопасный способ чтения — через МОДУЛЬ (`active.ACTIVE_PROVIDER`).

`from .active import ACTIVE_PROVIDER` связывает ЗНАЧЕНИЕ на момент импорта. После
`rebuild_provider()` такой модуль продолжил бы работать со старым провайдером — не падая,
ничего не логируя. Симптом ровно тот, который платформа уже однажды ловила: «заменил
мёртвый ключ в админке, ничего не починилось».

Поэтому два теста: поведенческий (пересборка видна снаружи) и структурный (в коде нет
формы импорта, которая это ломает).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import service.domain.client as client_pkg
from service.domain.client import active
from service.domain.client.calls import catalog, chat, streaming

# Имена, которые меняет `rebuild_provider`. Импортировать их ЗНАЧЕНИЕМ нельзя.
MUTABLE_NAMES = {"ACTIVE_PROVIDER", "_ACTIVE", "OPENAI_CLIENT"}

# ⚠️ ЯКОРЬ НА КОРЕНЬ ПАКЕТА, А НЕ НА `active.__file__`.
# Здесь стояло `Path(active.__file__).parent`, и это работало ровно до тех пор, пока
# `active` лежал в корне. `rglob` идёт только ВНИЗ: переехал бы `active` в подпакет — и
# область скана МОЛЧА сузилась бы до этого подпакета, а провайдеры выпали бы из проверки.
# Тест остался бы зелёным, перестав проверять то, ради чего написан.
CLIENT_PACKAGE = Path(client_pkg.__file__).parent


def test_rebuild_is_visible_to_every_module(monkeypatch):
    """Смена активного провайдера видна и `chat`, и `streaming`, и `catalog`.

    Проверяем не «функция отработала», а что ЧИТАТЕЛИ увидели новое значение: именно
    здесь ломается связывание значением на импорте.
    """
    monkeypatch.setattr(active, "ACTIVE_PROVIDER", "provider-after-rebuild")

    assert chat.active.ACTIVE_PROVIDER == "provider-after-rebuild"
    assert streaming.active.ACTIVE_PROVIDER == "provider-after-rebuild"
    assert catalog.active.ACTIVE_PROVIDER == "provider-after-rebuild"
    assert active.get_active_provider() == "provider-after-rebuild"


def test_no_module_imports_the_mutable_names_by_value():
    """⚠️ Структурная проверка: ни один модуль пакета не делает `from .active import <имя>`.

    Поведенческий тест выше поймал бы только те модули, которые в нём перечислены. Этот
    ловит любой новый — и в момент появления, а не когда админ пожалуется, что замена
    ключа не действует.
    """
    offenders: list[str] = []
    for path in sorted(CLIENT_PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if (node.module or "").endswith("active") or (node.level and node.module == "active"):
                bad = {alias.name for alias in node.names} & MUTABLE_NAMES
                if bad:
                    offenders.append(f"{path.name}:{node.lineno} импортирует {sorted(bad)}")

    assert not offenders, (
        "изменяемые имена связаны ЗНАЧЕНИЕМ — пересборка провайдера до них не дойдёт:\n"
        + "\n".join(offenders)
    )


def test_guard_scans_every_imported_module_of_the_package():
    """⚠️ МЕТА-ПРОВЕРКА: страж выше видит ВЕСЬ пакет, а не его часть.

    Структурный тест полезен ровно настолько, насколько широка его область скана. Сузить
    её можно случайно — переместив якорный модуль в подпакет, — и никто не заметит:
    тест продолжит проходить, просто перестав что-либо проверять.

    Поэтому сверяем область скана с тем, что реально загружено интерпретатором.
    """
    scanned = {p.resolve() for p in CLIENT_PACKAGE.rglob("*.py") if "__pycache__" not in p.parts}
    imported = {
        Path(module.__file__).resolve()
        for name, module in sys.modules.items()
        if name.startswith("service.domain.client") and getattr(module, "__file__", None)
    }

    missed = sorted(str(p) for p in imported - scanned)
    assert not missed, f"эти модули пакета вне области скана стража: {missed}"


def test_rebuild_returns_false_for_unknown_provider():
    """Обратная сторона: пересобрать несуществующего нельзя, и это НЕ исключение.

    Вызывающий (`/providers/keys`) обходит все известные имена; падение на одном
    оставило бы остальные ключи неприменёнными.
    """
    assert active.rebuild_provider("нет-такого-провайдера") is False
