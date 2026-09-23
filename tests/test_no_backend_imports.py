"""Сайдкар не имеет права импортировать код backend'а — ни модульно, ни лениво.

Зеркало `backend/tests/test_service_boundary.py`: тот сторожит границу со стороны
backend'а, а границу САМОГО сайдкара до этого не сторожил никто. И она протекала:
три импорта backend'а жили внутри `except`, молча падали и делали код мёртвым, но
выглядящим рабочим — `_read_compact_summary`, `load_memory_parts` и кэш сжатия
контекста (последний обходился в повторные ЛЛМ-вызовы на каждом сжатии).

Ленивые импорты (внутри функций) проверяются наравне с модульными ИМЕННО поэтому:
падение на импорте заметно сразу, а ленивое — только в рантайме и только если путь
побежит. Разбор AST ловит оба.

⚠️ ПОЧЕМУ ПРОВЕРКА ПО ПОДПАКЕТАМ, А НЕ ПО КОРНЮ. Раньше здесь стояло «корень
`service` запрещён» — движок звался `gpthub_agents`, и любой `service.*` был чужим
по определению. После переименования пакета в `service` (ради единообразия со всеми
сервисами) это правило стало ловить сам движок: его собственные импорты выглядят
ровно так же.

Отличить своё от чужого по имени КОРНЯ больше нельзя — только по подпакету. Ниже
перечислены те, которых у движка нет и не будет: это вертикальные срезы платформы,
её ORM и DI-контейнер. Список закрытый и проверяется на непересечение с реальным
деревом движка — иначе он тихо протухнет, когда у сайдкара появится свой `models`.
"""

from __future__ import annotations

import ast
import pathlib

# Корень пакета движка. Тесты намеренно не сканируем: они вправе импортировать что
# угодно для стенда.
_ROOT = pathlib.Path(__file__).resolve().parent.parent / "service"

# Подпакеты, существующие ТОЛЬКО у backend'а. Импорт любого из них означает, что код
# тянется в чужой контейнер, где его нет.
_BACKEND_ONLY = frozenset(
    {
        "services",  # вертикальные срезы платформы: chat, billing, admin, files…
        "models",  # ORM-модели и перечисления
        "composition",  # DI-контейнер
        "persistence",  # репозитории
    }
)


def _imported_paths(node: ast.AST) -> list[tuple[str, ...]]:
    """Пути импортируемых модулей (и `import x.y`, и `from x.y import z`)."""
    if isinstance(node, ast.Import):
        return [tuple(alias.name.split(".")) for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        # level > 0 — относительный импорт внутри пакета, он по определению свой
        if node.level or not node.module:
            return []
        return [tuple(node.module.split("."))]
    return []


def test_backend_only_subpackages_do_not_exist_here() -> None:
    """Список запрещённого не должен пересекаться со своим же деревом.

    Без этой проверки правило протухнет молча: заведи сайдкар собственный `models/`,
    и страж начнёт считать нарушением его нормальные внутренние импорты — а чинить
    это будут ослаблением стража.
    """
    collisions = sorted(name for name in _BACKEND_ONLY if (_ROOT / name).is_dir())
    assert not collisions, (
        "эти имена есть и у backend'а, и у движка — по ним больше нельзя отличить "
        f"чужой импорт от своего: {', '.join(collisions)}"
    )


def test_engine_never_imports_backend() -> None:
    offenders: list[str] = []

    for path in sorted(_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for parts in _imported_paths(node):
                if parts[:1] == ("service",) and len(parts) > 1 and parts[1] in _BACKEND_ONLY:
                    rel = path.relative_to(_ROOT.parent)
                    offenders.append(f"{rel}:{node.lineno} → {'.'.join(parts)}")

    assert not offenders, (
        "сайдкар импортирует код backend'а — в его контейнере этого модуля нет, "
        "так что путь либо мёртв, либо упадёт в рантайме:\n  " + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------- #
# Пакеты не затеняют свои подмодули                                            #
# --------------------------------------------------------------------------- #
def test_packages_do_not_shadow_their_submodules():
    """⚠️ `import <пакет>.<модуль> as m` обязан давать МОДУЛЬ, а не одноимённую функцию.

    Так было не всегда. `service/domain/tools/__init__.py` делал
    `from .web_search import web_search`, из-за чего атрибутом пакета `web_search`
    становилась ФУНКЦИЯ — и форма `import service.domain.tools.web_search as ws`
    возвращала её вместо модуля (Python берёт атрибут родителя). То же с
    `deep_research`.

    Проявлялось это не как ошибка, а как загадка: тест, которому нужно подменить
    атрибут В МОДУЛЕ, получал `AttributeError: function has no attribute ...` и был
    вынужден обходить пакет через `importlib.import_module`. Проверка структурная,
    потому что вернуть тень можно одной строкой реэкспорта.
    """
    import types

    import service.domain.tools.deep_research as tools_deep_research
    import service.domain.tools.web_search as tools_web_search

    assert isinstance(tools_web_search, types.ModuleType)
    assert isinstance(tools_deep_research, types.ModuleType)
