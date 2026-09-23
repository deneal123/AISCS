#!/usr/bin/env python3
"""Манифест конфигурации: сайдкар не читает переменных, о которых нигде не сказано.

Зачем отдельная проверка, а не «прибрались один раз». Разбор конфигурации показал
целый КЛАСС дефектов, а не отдельные промахи: переменная читается кодом, но не
объявлена нигде — ни в compose, ни в `.env.example`. Такие ручки нельзя ни найти,
ни покрутить без пересборки образа, и среди них оказались ЗАЩИТНЫЕ (потолки
tar-бомбы, лимит размера аудио). Разовая уборка этот класс не закрывает: следующая
такая переменная появится через месяц.

⚠️ Раньше проверка опиралась на `settings.toml` у каждого сайдкара. Слой убран:
он был у тонких legacy-сервисов и отсутствовал у backend и agents, то есть сам
стал тем расхождением, ради устранения которого затевался. Дефолты вернулись в код
(как у backend), а объявлением осталась ОДНА половина — `docker/.env.example`.
Ловушка от этого не ослабла: она всегда держалась на пункте «читается кодом →
объявлено», а не на существовании файла.

Запуск: `python scripts/check_settings_manifest.py` (в CI — джоба `integration`).
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / "docker" / ".env.example"

# Retained thin sidecar. Backend, agents, MemOS and ranking have their own
# typed contracts; retired GPTHub sidecars must not be added back here.
SIDECARS = ("whisper",)

# Инфраструктурные переменные: их задаёт платформа, а не настройка сервиса.
INFRA = {"PORT", "HOME", "PYTHONUNBUFFERED", "PATH"}


def _env_example_keys() -> set[str]:
    if not ENV_EXAMPLE.exists():
        return set()
    # `# VAR=...` считается объявлением тоже: раздел внутренних ручек сайдкаров
    # выписан закомментированным намеренно — это справка о том, что можно
    # переопределить, а не значения, которые надо задавать всем.
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    return set(re.findall(r"^#?\s*([A-Z_0-9]+)=", text, re.M))


def _env_vars_read_by(service: pathlib.Path) -> set[str]:
    """Имена, которые сервис читает из окружения — по AST, а не по grep.

    Grep поймал бы и строки в комментариях. Нас интересуют только настоящие вызовы
    `os.environ.get("X")` / `os.getenv("X")` / `os.environ["X"]`.
    """
    found: set[str] = set()
    # Код живёт в `service/` — раскладка выровнена под backend. Раньше здесь стоял
    # `glob("*.py")` по корню сервиса; после переезда он не нашёл бы ни одного файла
    # и проверка молча проходила бы на пустом множестве.
    for path in sorted(service.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in ("get", "getenv"):
                    target = getattr(func.value, "attr", None) or getattr(func.value, "id", None)
                    if target in ("environ", "os"):
                        name = node.args[0].value
            elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                target = getattr(node.value, "attr", None)
                if target == "environ":
                    name = node.slice.value
            if isinstance(name, str) and re.fullmatch(r"[A-Z_][A-Z_0-9]*", name):
                found.add(name)
    return found


def main() -> int:
    problems: list[str] = []
    env_example = _env_example_keys()

    for name in SIDECARS:
        code = ROOT / name / "service"
        if not code.is_dir():
            problems.append(f"{name}: нет каталога service/ — раскладка разошлась с ожидаемой")
            continue

        read = _env_vars_read_by(code)
        if not read:
            # Пустое множество — почти наверняка сломанный путь, а не сервис без
            # настроек. Молчаливое «всё хорошо» здесь опаснее ложной тревоги.
            problems.append(f"{name}: не найдено НИ ОДНОГО чтения окружения — проверьте путь")
            continue

        orphan = sorted(v for v in read - INFRA if v not in env_example)
        if orphan:
            problems.append(
                f"{name}: читается кодом, но не объявлено в docker/.env.example: "
                + ", ".join(orphan)
            )

    if problems:
        print("Манифест конфигурации разошёлся с кодом:\n")
        for item in problems:
            print(f"  * {item}")
        print(
            "\nПочему это гейт: незаявленную ручку нельзя ни найти, ни покрутить без\n"
            "пересборки образа. Среди таких уже оказывались защитные лимиты."
        )
        return 1

    print(f"Манифест конфигурации в порядке: проверено сервисов — {len(SIDECARS)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
