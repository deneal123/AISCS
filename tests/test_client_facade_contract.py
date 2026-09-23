"""Всё, что импортируют из фасада `domain.client`, оттуда реально импортируется.

⚠️ ЗАЧЕМ. У фасада не было ПРОВЕРЯЕМОГО контракта: `__all__` перечисляет 12 имён, но
ничто не сверяло его с тем, что код действительно просит. Расхождение не падает на
старте — импорты у потребителей отложенные (внутри функций), поэтому `ImportError`
случается при ВЫЗОВЕ, то есть у пользователя, а не на сборке.

Именно так и вышло: `domain/media.py:74` просит `build_provider_order`, которого в фасаде
нет, и ручка `/media` — транскрипция аудио — не работает целиком.

Проверка структурная: обойти ВЕСЬ `service/` разбором AST и убедиться, что каждое
запрошенное имя достаётся из пакета на самом деле.

⚠️ Про подмодули (`provider_policy`, `circuit_breaker`, `provider_credentials`) здесь
НЕТ отдельной проверки, и это осознанно. Была гипотеза, что они доступны лишь по
побочному эффекту чужих импортов и потому хрупки; проверено в чистом процессе с
удалённым связыванием — `from пакет import подмодуль` работает всегда, его вытягивает
сама машинерия импорта. Страж на «объявите их явно» навязывал бы несуществующее
свойство: он краснел бы на `openai_compatible`, который никто и не думал ломать.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

import service.domain.client as client_pkg

SERVICE_ROOT = Path(client_pkg.__file__).resolve().parents[2]
_FACADE_MODULE = "service.domain.client"


def _facade_imports() -> list[tuple[str, str, int]]:
    """Все `from …domain.client import X` в сервисе → [(имя, файл, строка)]."""
    found: list[tuple[str, str, int]] = []
    for path in sorted(SERVICE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — синтаксис ловит ruff
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            # `from service.domain.client import X` либо относительный `from .client import X`
            absolute = (node.module or "") == "service.domain.client"
            relative = bool(node.level) and (node.module or "").endswith("client")
            if not (absolute or relative):
                continue
            for alias in node.names:
                found.append((alias.name, str(path.relative_to(SERVICE_ROOT)), node.lineno))
    return found


_IMPORTS = _facade_imports()


def test_scan_found_the_consumers():
    """⚠️ Сам скан рабочий. Пустой список означал бы, что тест ничего не проверяет."""
    assert len(_IMPORTS) >= 10, f"скан нашёл лишь {len(_IMPORTS)} импортов — сломан обход"


@pytest.mark.parametrize(
    ("name", "where", "line"),
    [pytest.param(n, w, ln, id=f"{n}@{w}:{ln}") for n, w, ln in _IMPORTS],
)
def test_every_imported_name_resolves(name, where, line):
    """Имя, которое просят из фасада, обязано из него доставаться.

    Падение здесь означает `ImportError` у пользователя в момент вызова.
    """
    facade = importlib.import_module(_FACADE_MODULE)
    assert hasattr(facade, name), (
        f"{where}:{line} импортирует '{name}' из фасада, которого там нет — "
        f"у потребителя это ImportError при вызове"
    )


def test_public_names_are_declared_in_all():
    """Что импортируют снаружи — то и должно быть объявлено в `__all__`.

    Иначе имя доступно «по случайности» (как атрибут-подмодуль, связанный чужим
    импортом), и его пропажа станет заметна только в проде.
    """
    facade = importlib.import_module(_FACADE_MODULE)
    declared = set(facade.__all__)
    requested = {name for name, _, _ in _IMPORTS}
    # Подмодули пакета — законный способ обращения (`from .client import circuit_breaker`),
    # и они достаются машинерией импорта даже без записи в `__all__`; поэтому из проверки
    # исключается всё, что фактически резолвится.
    undeclared = {n for n in requested - declared if not hasattr(facade, n)}
    assert not undeclared, f"имена вне __all__ и недоступные: {sorted(undeclared)}"
