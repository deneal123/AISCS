#!/usr/bin/env python3
"""Контракт окружения: шаблон, две конфигурации и то, что реально читает код.

Проверка отвечает на три вопроса, на которые раньше отвечали два разных скрипта
(check_settings_manifest.py и check_sidecar_env.py), причём отвечали уже неверно:
каталогов удалённых сайдкаров больше нет, и оба гейта были красными по построению.

1. Каждый ключ docker/.env.example есть в docker/.env.dev и docker/.env.prod,
   и ни в одном файле нет повторов. Значения не печатаются никогда.
2. Каждое имя, которое читает живой код (backend/service и generator/service)
   через os.environ/os.getenv, либо объявлено в .env.example, либо доставляется
   в контейнер из compose, либо сознательно оставлено на дефолте кода — и тогда
   оно перечислено ниже с причиной.
3. Каждый ключ, который compose подставляет в контейнер как GENERATOR_*,
   действительно читается кодом генератора: иначе это опечатка, которая молча
   ничего не настраивает.

Зависимостей нет — только stdlib.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSES = ("docker/docker-compose.dev.yaml", "docker/docker-compose.yaml")
ENV_EXAMPLE = "docker/.env.example"
ENV_FILES = ("docker/.env.dev", "docker/.env.prod")
CODE_ROOTS = ("backend/service", "generator/service")

KEY = re.compile(r"^([A-Z_][A-Z0-9_]*)=", re.M)
READ = (
    re.compile(r"os\.environ\.get\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']"),
    re.compile(r"os\.getenv\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']"),
    re.compile(r"os\.environ\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']\s*\]"),
    re.compile(r"os\.environ\.setdefault\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']"),
)

# Имена, которые код читает, но которые НЕ обязаны быть в env: у них осмысленный
# дефолт в коде, и пустое значение было бы хуже отсутствия. Каждое — с причиной,
# чтобы список нельзя было пополнить молча.
CODE_DEFAULT = {
    # Генератор: тюнинг и необязательные кеши. Значение по умолчанию — рабочее.
    "GENERATOR_ALLOCATOR_TUNING": "тюнинг аллокатора, дефолт в коде",
    "GENERATOR_CACHE_MAX_BYTES": "бюджет кеша, дефолт в коде",
    "GENERATOR_CNS_MODEL_PATH": "путь к модели, задаётся только для своей сборки",
    "GENERATOR_CONNECTOME_DIR": "каталог коннектома, задаётся только для своей сборки",
    "GENERATOR_FEEDBACK_CACHE_BYTES": "бюджет кеша обратной связи, дефолт в коде",
    "GENERATOR_FULL_CONTROL": "политика контроля: omitted по умолчанию",
    "GENERATOR_FULL_PAUSE": "каталог паузы: выключена по умолчанию",
    "GENERATOR_GPU_ZERO_EDGE_REPAIR": "флаг ремонта рёбер, дефолт в коде",
    "GENERATOR_MODEL_PATH": "путь к модели, задаётся только для своей сборки",
    "GENERATOR_NARROW_CELL_CACHE": "кеш сокращённых клеток: выключен по умолчанию",
    "GENERATOR_OUTPUT_SELECTION_CACHE": "таблица выбора: выключена по умолчанию",
    "GENERATOR_RECORDING_COEFFICIENT_CACHE": "кеш коэффициентов: выключен по умолчанию",
    "GENERATOR_SOURCE_READ_WORKERS": "число читателей: дефолт в коде",
    # Backend: расписания и переопределения, у которых дефолт — рабочая величина.
    "NUMBA_CACHE_DIR": "задаётся в Dockerfile генератора, код лишь страхует дефолт",
    "CELERY_BROKER_URL": "алиас CELERY__BROKER_URL, читается как запасной",
    "CHAT_RETENTION_SCHEDULE_SECONDS": "расписание, дефолт в коде",
    "NOTIFICATIONS_SCHEDULE_SECONDS": "расписание, дефолт в коде",
    "PAYMENT_RECONCILE_SCHEDULE_SECONDS": "расписание, дефолт в коде",
    "PROVIDER_RECHECK_SCHEDULE_SECONDS": "расписание, дефолт в коде",
    "RESERVATION_CLEANUP_SCHEDULE_SECONDS": "расписание, дефолт в коде",
    "OPENROUTER_USD_TO_RUB": "курс, дефолт в коде",
    "SESSION_ENCRYPTION_KEY": "необязательный ключ шифрования сессий",
    "SIMULATION_QUEUE": "имя очереди, дефолт в коде",
    "SSL_CERT_FILE": "стандартная переменная TLS-стека, не наша настройка",
    "STORAGE_ROOT": "алиас STORAGE__ROOT, читается как запасной",
    "USE_CELERY": "устаревший алиас USE_CEREMONY→USE_CELERY, дефолт в коде",
    # Остатки удалённых сайдкаров: читаются только если заданы, и никто их не задаёт.
    "MEM0_API_KEY": "остаток сайдкара memos",
    "MEM0_APP_ID": "остаток сайдкара memos",
    "MEM0__API_KEY": "остаток сайдкара memos",
    "MEM0__APP_ID": "остаток сайдкара memos",
    "MEM0AI_API_KEY": "остаток сайдкара memos",
    "SERVICE__MEM0_API_KEY": "остаток сайдкара memos",
    "AGENTS__MEM0_API_KEY": "остаток сайдкара memos",
    "AGENTS__MEM0_APP_ID": "остаток сайдкара memos",
    "WORKSPACE_COORDINATION_SECRET": "остаток сайдкара workspace",
    "WORKSPACE_COORDINATOR_URL": "остаток сайдкара workspace",
}


def keys_of(path: pathlib.Path) -> list[str]:
    return KEY.findall(path.read_text(encoding="utf-8"))


def service_block(path: pathlib.Path, service: str) -> str:
    """Тело одного сервиса: от `\n  имя:\n` до следующего сервиса верхнего уровня."""
    body = path.read_text(encoding="utf-8")
    match = re.search(r"\n  " + re.escape(service) + r":\n(.*?)(?=\n  [a-z0-9-]+:\n|\n(?:volumes|networks):)", body, re.S)
    return match.group(1) if match else ""


def compose_environment(path: pathlib.Path, service: str | None = None) -> set[str]:
    """Ключи, которые compose кладёт в контейнер: environment одного или всех сервисов."""
    body = path.read_text(encoding="utf-8") if service is None else service_block(path, service)
    found: set[str] = set()
    for line in body.splitlines():
        stripped = line.strip()
        match = re.match(r"([A-Z_][A-Z0-9_]*):", stripped)
        if match and line.startswith(" " * 6) and not line.startswith(" " * 7):
            found.add(match.group(1))
    return found


def code_reads() -> set[str]:
    found: set[str] = set()
    for rel in CODE_ROOTS:
        for path in (ROOT / rel).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for pattern in READ:
                found.update(pattern.findall(text))
    return found


def referenced(name: str) -> bool:
    """Имя упоминается в коде генератора или в его Dockerfile.

    Динамические чтения (`os.environ.get(name)` по кортежу имён) регуляркой по
    вызову не ловятся, поэтому «читается ли ключ» решается упоминанием имени:
    если строки нет нигде — это опечатка в compose, а не настройка.
    """
    pattern = re.compile(r"\b" + re.escape(name) + r"\b")
    for path in (ROOT / "generator").rglob("*"):
        if path.is_file() and path.suffix in {".py", ".toml", ".yaml", ".yml"} or path.name == "Dockerfile":
            try:
                if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                    return True
            except OSError:
                continue
    return False


def env_drift(example: pathlib.Path, paths: list[pathlib.Path]) -> list[str]:
    """Сверить все ключи существующих env, не раскрывая их значения в диагностике."""
    expected = set(keys_of(example))
    problems = []
    for path in paths:
        # В чистом клоне реальные секреты отсутствуют намеренно.
        if not path.is_file():
            continue
        actual = keys_of(path)
        missing = sorted(expected - set(actual))
        duplicates = sorted(key for key in set(actual) if actual.count(key) > 1)
        if missing:
            problems.append(f"{path.name}: отсутствуют ключи образца: {', '.join(missing)}")
        if duplicates:
            problems.append(f"{path.name}: повторяются ключи: {', '.join(duplicates)}")
    return problems


def check() -> list[str]:
    problems = env_drift(ROOT / ENV_EXAMPLE, [ROOT / rel for rel in ENV_FILES])

    declared = set(keys_of(ROOT / ENV_EXAMPLE))
    delivered: set[str] = set()
    for rel in COMPOSES:
        delivered |= compose_environment(ROOT / rel)

    reads = code_reads()
    undeclared = sorted(reads - declared - delivered - CODE_DEFAULT.keys())
    if undeclared:
        problems.append(
            "код читает переменные, которых нет ни в .env.example, ни в compose, "
            "ни в CODE_DEFAULT: " + ", ".join(undeclared)
        )
    stale = sorted(set(CODE_DEFAULT) - reads)
    if stale:
        problems.append("CODE_DEFAULT перечисляет имена, которые код уже не читает: " + ", ".join(stale))

    generator_keys: set[str] = set()
    for rel in COMPOSES:
        generator_keys |= compose_environment(ROOT / rel, "generator")
    unread = sorted(
        key for key in generator_keys
        if key.startswith("GENERATOR_") and not referenced(key)
    )
    if unread:
        problems.append(
            "compose подставляет генератору ключи, которых код не читает: " + ", ".join(unread)
        )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("КОНТРАКТ ОКРУЖЕНИЯ НАРУШЕН:", file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1
    print(
        "  ok  ключей в шаблоне: "
        + str(len(keys_of(ROOT / ENV_EXAMPLE)))
        + "; читает код: "
        + str(len(code_reads()))
        + "; обе конфигурации совпадают с шаблоном"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
