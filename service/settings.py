"""Загрузка `settings.toml` — объявленные несекретные дефолты сервиса.

Три слоя, приоритет `env > settings.toml > дефолт в коде`:

  * дефолт в коде — пол. Сервис обязан подниматься без TOML и без env (тесты, CI,
    голый `docker run`), поэтому файл необязателен и его отсутствие не ошибка;
  * `settings.toml` — ответ на вопрос «какие вообще есть ручки». До него часть
    лимитов (в том числе защитных) существовала только внутри `os.environ.get` и
    не была объявлена нигде: узнать о них можно было лишь чтением кода, а
    поменять — только пересборкой образа;
  * env — секреты и переопределение под окружение, всегда выигрывает.

Почему через `os.environ.setdefault`, а не через свой объект конфигурации:
сервис уже читает окружение напрямую, и подкладывание дефолтов ПОД него делает
приоритет верным по построению — уже заданную переменную setdefault не трогает.
Второй источник истины при этом не появляется: TOML лишь заполняет пустоты.

⚠️ Секретам здесь не место: файл коммитится. Проверку на это делает
`scripts/check_settings_manifest.py` в суперпроекте.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

# Путь можно переопределить — это аварийный ход для оператора, когда правку нужно
# внести без пересборки образа.
_ENV_OVERRIDE = "GPTHUB_SETTINGS_TOML"
# `.parent.parent` — settings.toml лежит в КОРНЕ сервиса, рядом с pyproject.toml,
# а не внутри пакета: это конфигурация сервиса, а не его код.
_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "settings.toml"


def _flatten(table: dict, prefix: str = "") -> dict[str, str]:
    """`[limits] max_rows = 200` → `{"DUCKDB_MAX_ROWS": "200"}`.

    Имена НЕ придумываются: секция задаёт префикс, ключ — остаток. Так переменные
    в TOML и в compose совпадают буква в букву, и ни одна настройка не теряется
    при переезде.
    """
    out: dict[str, str] = {}
    for key, value in table.items():
        name = f"{prefix}{key}".upper()
        if isinstance(value, dict):
            out.update(_flatten(value, prefix=f"{name}_"))
        elif isinstance(value, bool):
            # Именно "true"/"false": так их пишет compose, и так их читает код.
            out[name] = "true" if value else "false"
        else:
            out[name] = str(value)
    return out


def load() -> dict[str, str]:
    """Подложить дефолты из TOML под окружение. Возвращает применённое — для логов."""
    path = Path(os.environ.get(_ENV_OVERRIDE) or _DEFAULT_PATH)
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        data = tomllib.load(fh)

    applied: dict[str, str] = {}
    for name, value in _flatten(data).items():
        # setdefault: реальная переменная окружения всегда сильнее файла.
        if os.environ.get(name) in (None, ""):
            os.environ[name] = value
            applied[name] = value
    return applied


# Загрузка происходит НА ИМПОРТЕ модуля. Так вызывающему достаточно обычного
# `import settings` в общем блоке импортов — не нужно ставить вызов между
# импортами и ловить E402. Порядок при этом гарантирован: тот, кто читает
# окружение, импортирует этот модуль раньше, чем прочтёт хоть одну переменную.
APPLIED = load()
