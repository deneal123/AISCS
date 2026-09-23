"""Отложенные импорты внутри функций РЕЗОЛВЯТСЯ.

⚠️ ЗАЧЕМ ОТДЕЛЬНЫЙ СТРАЖ, ЕСЛИ ЕСТЬ ИМПОРТ МОДУЛЕЙ. Импорт пакета проверяет только то,
что выполняется на верхнем уровне. Импорт внутри функции выполняется в момент ВЫЗОВА —
и если ветка редкая, он может быть сломан месяцами, ничего не выдавая.

Так и было: `resilience/provider_policy.py` делал `from .registry import PROVIDER_MODULES`
после переезда модуля в подпакет, то есть ссылался на несуществующий
`client.resilience.registry` вместо `client.registry`. Ветка срабатывает, только когда
`hard_off` зовут БЕЗ явного списка провайдеров — а штатный путь список передаёт. На
пустом списке (старт без настроенных провайдеров) падал сбор каталога ЦЕЛИКОМ, и каталог
оставался пустым; наружу это выглядело как «моделей нет».

Отложенных импортов в сервисе много и они осмысленны — ими разрывают циклы и удешевляют
старт. Тем важнее, чтобы за ними кто-то следил.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SERVICE = _ROOT / "service"


def _deferred_relative_imports() -> list[tuple[str, int, str]]:
    """Все `from .X import ...` и `from ..X import ...` ВНУТРИ функций."""
    found: list[tuple[str, int, str]] = []
    for path in _SERVICE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.ImportFrom) and node.level:
                    pkg = path.relative_to(_ROOT).parent.as_posix().replace("/", ".")
                    # `level` точек вверх от пакета, в котором лежит файл.
                    parts = pkg.split(".")
                    base = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
                    target = ".".join([*base, node.module]) if node.module else ".".join(base)
                    found.append((str(path.relative_to(_ROOT)), node.lineno, target))
    return found


def test_there_are_deferred_relative_imports_to_check():
    """Контроль предпосылки: если их не осталось, страж молча проверяет пустоту."""
    assert len(_deferred_relative_imports()) >= 1


@pytest.mark.parametrize(
    ("where", "line", "target"),
    _deferred_relative_imports(),
    ids=lambda v: str(v),
)
def test_deferred_relative_import_points_at_a_real_module(where, line, target):
    """Модуль, на который ссылается отложенный импорт, обязан существовать.

    `find_spec` не ИСПОЛНЯЕТ модуль — только проверяет, что он находится. Этого хватает:
    ловим именно переезды и опечатки в пути, не трогая побочные эффекты импорта.
    """
    spec = importlib.util.find_spec(target)
    assert spec is not None, (
        f"{where}:{line}: отложенный импорт ссылается на несуществующий модуль "
        f"'{target}' — сработает только когда исполнится эта ветка"
    )


def _deferred_names_from_packages() -> list[tuple[str, int, str, str]]:
    """`from .pkg import ИМЯ` внутри функций → (файл, строка, пакет, имя).

    ⚠️ ЭТО ДРУГОЙ КЛАСС, ЧЕМ ПРОВЕРКА ВЫШЕ. Там цель — модуль, и `find_spec` его находит.
    Здесь импортируется ИМЯ ИЗ ПАКЕТА (`from . import openrouter_client`), а пакет
    существует ВСЕГДА — `find_spec` зелёный, даже когда имени в пакете давно нет.

    Ровно так `health.py` тянул `openrouter_client` из фасада после переезда провайдеров
    в подпакет: `from . import openrouter_client` — пакет `service.domain.client` на
    месте, а имени нет, и вся ручка `/providers/health` падала 500-й (пустая админ-панель).
    """
    found: list[tuple[str, int, str, str]] = []
    for path in _SERVICE.rglob("*.py"):
        if path.name == "__init__.py":
            continue  # реэкспорты пакета — не потребитель, а поставщик имён
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if not (isinstance(node, ast.ImportFrom) and node.level):
                    continue
                pkg = path.relative_to(_ROOT).parent.as_posix().replace("/", ".")
                parts = pkg.split(".")
                base = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
                target = ".".join([*base, node.module]) if node.module else ".".join(base)
                for alias in node.names:
                    if alias.name != "*":
                        found.append(
                            (str(path.relative_to(_ROOT)), node.lineno, target, alias.name)
                        )
    return found


@pytest.mark.parametrize(
    ("where", "line", "pkg", "name"),
    _deferred_names_from_packages(),
    ids=lambda v: str(v),
)
def test_deferred_imported_name_actually_exists(where, line, pkg, name):
    """Импортируемое ИМЯ должно существовать в модуле/пакете, откуда его тянут.

    Импортируем сам объект — это и есть то, что делает прод при исполнении ветки. Модуль
    без побочных эффектов на импорте у нас нет (фасад провайдеров их и так исполняет при
    сборке), поэтому проверка честная и дешёвая.
    """
    module = importlib.import_module(pkg)
    if hasattr(module, name):
        return  # имя-атрибут (функция/класс/реэкспорт) на месте

    # ⚠️ Имя может быть ПОДМОДУЛЕМ, который ещё не импортирован — тогда `hasattr` на
    # пакете его не видит, хотя `from pkg import submodule` сработает. Отличаем настоящую
    # пропажу от неимпортированного подмодуля попыткой найти его спеку.
    try:
        spec = importlib.util.find_spec(f"{pkg}.{name}")
    except (ImportError, AttributeError):
        spec = None
    assert spec is not None, (
        f"{where}:{line}: '{name}' не существует в '{pkg}' — ни атрибутом, ни подмодулем. "
        f"Отложенный импорт из пакета падает ImportError только при исполнении ветки, а "
        f"`find_spec` на сам пакет этого не ловит."
    )
