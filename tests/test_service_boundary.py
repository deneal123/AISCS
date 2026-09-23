"""Backend не имеет права импортировать код сайдкара.

Зеркало `agents/tests/test_no_backend_imports.py`. Раньше здесь стоял страж границы
общего пакета `gpthub_core` — он следил, чтобы ПЕРЕНОСИМОЕ ядро не тянуло за собой
backend. Пакета больше нет: конфигурация, капабилити и провод разъехались по
владельцам, а совпадение форм держат контракт в `/health` и сверка в CI.

Осталась ровно одна граница, которую можно нарушить незаметно: импортировать чужой
сервис напрямую. В контейнере backend'а пакета `gpthub_agents` нет, поэтому такой
импорт либо мёртв (под `except`, как это уже было в сайдкаре — три молча неработающих
пути), либо упадёт в рантайме на первом обращении.

Ленивые импорты проверяются наравне с модульными: падение на импорте видно сразу, а
ленивое — только когда путь реально побежит. Разбор AST ловит оба.
"""

from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent / "service"

# Пространства имён сайдкара. `api` не включаем: это слишком общее слово, а свой
# HTTP-слой backend держит в `service/services/*/presentation`.
# `gpthub_core` из списка убран: пакет удалён, импортировать его нечем, и эта
# половина утверждения не могла сработать ни при каких условиях. Страж, часть
# которого физически не способна упасть, вводит в заблуждение насчёт того, что
# он на самом деле проверяет.
#
# ⚠️ ПО ПОДПАКЕТАМ, А НЕ ПО КОРНЮ. Раньше здесь стоял корень `gpthub_agents` — имя
# пакета сайдкара, чужое по определению. Сайдкар переименовал свой пакет в `service`
# ради единообразия, и по корню отличить его от НАШЕГО `service` стало нельзя.
#
# Различает подпакет: перечисленные ниже есть у сайдкара и отсутствуют у нас. Их
# непересечение с нашим деревом проверяется отдельным тестом — иначе правило тихо
# протухнет, когда у backend появится собственный `api` или `domain` на верхнем уровне.
_SIDECAR_ONLY = frozenset(
    {"api", "application", "domain", "presentation", "schemas", "events", "contracts"}
)


def _module_paths(node: ast.AST) -> list[tuple[str, ...]]:
    """Пути модулей, которые импортирует узел (`import x.y` и `from x.y import z`)."""
    if isinstance(node, ast.Import):
        return [tuple(alias.name.split(".")) for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level or not node.module:  # относительный импорт — по определению свой
            return []
        return [tuple(node.module.split("."))]
    return []


def test_sidecar_only_subpackages_do_not_exist_here() -> None:
    """Список запрещённого не должен пересекаться с нашим же деревом.

    Без этого правило протухнет молча: заведи backend собственный `service/api/`, и
    страж начнёт считать нарушением наши нормальные внутренние импорты — а чинить
    это будут ослаблением стража.
    """
    collisions = sorted(
        name
        for name in _SIDECAR_ONLY
        if (_ROOT / name).is_dir() or (_ROOT / f"{name}.py").is_file()
    )
    assert not collisions, (
        "эти имена есть и у сайдкара, и у нас — по ним больше нельзя отличить "
        f"чужой импорт от своего: {', '.join(collisions)}"
    )


def test_backend_never_imports_sidecar() -> None:
    offenders: list[str] = []

    for path in sorted(_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for parts in _module_paths(node):
                if parts[:1] == ("service",) and len(parts) > 1 and parts[1] in _SIDECAR_ONLY:
                    name = ".".join(parts)
                    offenders.append(f"{path.relative_to(_ROOT.parent)}:{node.lineno} → {name}")

    assert not offenders, (
        "backend импортирует код сайдкара — в его контейнере этого модуля нет, "
        "так что путь либо мёртв, либо упадёт в рантайме:\n  " + "\n  ".join(offenders)
    )
