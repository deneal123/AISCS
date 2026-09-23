"""Ограничитель роста модулей и функций сайдкара.

⚠️ ВТОРАЯ КОПИЯ: первая живёт в `backend/scripts/`. Общего пакета не заводим тем же
решением, что и по контракту и по базе клиента — сабмодуль обязан проверяться в
одиночку, без установки соседа. Скрипт на голом stdlib, расходиться копиям нечем.

Зачем понадобился здесь. У сайдкара ограничителя не было ВООБЩЕ: единственным
упоминанием сложности был `max-complexity = 70` у ruff — часовой, который не срабатывал
никогда. За это время выросли `domain/base.py` (1071 строка) и `domain/client/__init__.py`
(680 строк ЛОГИКИ в `__init__` пакета, то есть исполняемых при каждом импорте), а три
функции перевалили за 236, 265 и 305 строк.

⚠️ ПОРОГИ НИЖЕ, ЧЕМ У BACKEND (500/150/30 против 750/250/70), и это не расхождение
стиля. У backend это монолит с исторически крупными модулями, где 750 — компромисс с
реальностью. Здесь сервис одноцелевой и втрое меньше, а длинные функции — ровно тот
долг, который сейчас гасится: ставить порог выше значило бы узаконить его.

Долг фиксируется храповиком (`complexity_baseline.json`), не амнистией: записанное не
может расти, незаписанное роняет проверку.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Thresholds:
    max_lines_per_file: int
    max_function_length: int
    max_cyclomatic_complexity: int
    max_import_fan_out: int
    max_import_fan_in: int


class CyclomaticVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.complexity = 1

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(
            node,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.IfExp,
                ast.ExceptHandler,
                ast.With,
                ast.AsyncWith,
                ast.Assert,
                ast.Try,
            ),
        ):
            self.complexity += 1
        if isinstance(node, ast.BoolOp):
            self.complexity += max(len(node.values) - 1, 0)
        if isinstance(node, ast.Match):
            self.complexity += len(node.cases)
        super().generic_visit(node)


class QualityError(RuntimeError):
    pass


# Файл известного долга. Смысл — ХРАПОВИК, а не амнистия:
#   * нарушения, которых в нём нет, роняют проверку (новый долг не заводится);
#   * записанные нарушения не должны РАСТИ — стало хуже, проверка падает;
#   * стало лучше — запись просто просят обновить.
#
# Зачем понадобился: проверка была настроена, но pre-commit ни разу не устанавливался,
# поэтому четыре нарушения копились годами (`chat_worker_tasks.py` — 1609 строк при
# пороге 750). Включить её «как есть» значило бы заблокировать любой коммит, а удалить —
# потерять единственный ограничитель роста. Храповик позволяет и то и другое: долг
# зафиксирован в отслеживаемом файле, виден в ревью и может только уменьшаться.
#
# ⚠️ Путь считается от САМОГО скрипта, а не от `--root`: root указывает на `service/`,
# и относительный путь искал бы `service/scripts/…`, молча не находил файл и объявлял
# ВЕСЬ известный долг новым.
BASELINE_FILE = Path(__file__).resolve().parent / "complexity_baseline.json"


def _apply_baseline(violations: list[tuple[str, int, str]], root: Path) -> None:
    baseline_path = BASELINE_FILE
    baseline: dict[str, int] = {}
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8")).get("allowed", {})

    failures: list[str] = []
    for key, value, message in violations:
        allowed = baseline.get(key)
        if allowed is None:
            failures.append(f"НОВОЕ нарушение: {message}")
        elif value > allowed:
            failures.append(f"Долг ВЫРОС (было {allowed}): {message}")
        elif value < allowed:
            # ⚠️ Это НЕ придирка, а суть храповика. Запись — то, сколько долга есть
            # сейчас, а не сколько его разрешено набрать. Пока она больше факта, разница
            # — это молчаливое право отрасти обратно, и оно уже реализовывалось: три
            # записи ушли в запас за две фазы, никем не замеченные, потому что прогон
            # был зелёный. Поэтому «стало лучше» тоже требует правки файла.
            failures.append(f"Долг УМЕНЬШИЛСЯ (было {allowed}, стало {value}): подтяните {key}")

    # Запись, под которой нарушения больше нет, — та же дыра, только с другой стороны:
    # функция ушла под порог, ключ остался, и обратный рост до прежней нормы пройдёт
    # молча. Правило одно на все случаи: файл — точное зеркало текущих нарушений.
    current = {key for key, _, _ in violations}
    for key in sorted(set(baseline) - current):
        failures.append(f"Долг ПОГАШЕН: уберите {key} из {BASELINE_FILE.name}")

    if failures:
        failures.append(
            f"\n{BASELINE_FILE.name} — инвентарь долга, а не разрешение его набрать: "
            "в нём должно стоять ровно то, что есть сейчас. Любое расхождение правится "
            "здесь же, и это видно в ревью."
        )
        raise QualityError("\n".join(sorted(failures)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="service")
    # `--critical` задаёт, для каких модулей меряется связность (fan-in/fan-out).
    # У сайдкара это движок и его оркестрация: именно там расползание импортов
    # означает, что слой перестал быть слоем.
    parser.add_argument("--critical", nargs="+", default=["service/domain", "service/application"])
    parser.add_argument("--max-lines-per-file", type=int, default=500)
    parser.add_argument("--max-function-length", type=int, default=150)
    parser.add_argument("--max-cyclomatic-complexity", type=int, default=30)
    parser.add_argument("--max-import-fan-out", type=int, default=60)
    parser.add_argument("--max-import-fan-in", type=int, default=80)
    return parser.parse_args()


def module_name(root: Path, file_path: Path) -> str:
    return ".".join(file_path.relative_to(root).with_suffix("").parts)


def imported_module(base_module: str, node_module: str | None, level: int) -> str | None:
    if level == 0:
        return node_module
    parts = base_module.split(".")
    if len(parts) < level:
        return None
    prefix = parts[: len(parts) - level]
    if node_module:
        prefix.extend(node_module.split("."))
    return ".".join(prefix)


def collect_python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def function_nodes(tree: ast.AST) -> list[ast.AST]:
    return [
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def evaluate(root: Path, critical_dirs: list[Path], thresholds: Thresholds) -> None:
    files = collect_python_files(root)
    violations: list[tuple[str, int, str]] = []
    import_graph: dict[str, set[str]] = defaultdict(set)
    critical_modules: set[str] = set()

    for file_path in files:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        module = module_name(root, file_path)

        if any(file_path.is_relative_to(critical_dir) for critical_dir in critical_dirs):
            critical_modules.add(module)

        rel = file_path.relative_to(root).as_posix()

        lines = len(source.splitlines())
        if lines > thresholds.max_lines_per_file:
            violations.append(
                (
                    f"{rel}::lines",
                    lines,
                    f"{rel}: lines={lines} exceeds "
                    f"max_lines_per_file={thresholds.max_lines_per_file}",
                )
            )

        for func in function_nodes(tree):
            func_len = (func.end_lineno or func.lineno) - func.lineno + 1
            if func_len > thresholds.max_function_length:
                violations.append(
                    (
                        # Ключ БЕЗ номера строки: иначе любая правка выше по файлу
                        # сдвигала бы его и «новое» нарушение появлялось на ровном месте.
                        f"{rel}::{func.name}::length",
                        func_len,
                        f"{rel}:{func.lineno} {func.name} length={func_len} exceeds "
                        f"max_function_length={thresholds.max_function_length}",
                    )
                )
            visitor = CyclomaticVisitor()
            visitor.visit(func)
            if visitor.complexity > thresholds.max_cyclomatic_complexity:
                violations.append(
                    (
                        f"{rel}::{func.name}::complexity",
                        visitor.complexity,
                        f"{rel}:{func.lineno} {func.name} "
                        f"complexity={visitor.complexity} exceeds "
                        f"max_cyclomatic_complexity={thresholds.max_cyclomatic_complexity}",
                    )
                )

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_graph[module].add(alias.name)
            if isinstance(node, ast.ImportFrom):
                imported = imported_module(module, node.module, node.level)
                if imported:
                    import_graph[module].add(imported)

    fan_in = Counter()
    fan_out = {module: len(imports) for module, imports in import_graph.items()}

    for _module, imports in import_graph.items():
        for imported in imports:
            if imported in critical_modules:
                fan_in[imported] += 1

    for module in critical_modules:
        out = fan_out.get(module, 0)
        if out > thresholds.max_import_fan_out:
            violations.append(
                (
                    f"{module}::fan_out",
                    out,
                    f"{module}: fan_out={out} exceeds "
                    f"max_import_fan_out={thresholds.max_import_fan_out}",
                )
            )
        fin = fan_in.get(module, 0)
        if fin > thresholds.max_import_fan_in:
            violations.append(
                (
                    f"{module}::fan_in",
                    fin,
                    f"{module}: fan_in={fin} exceeds "
                    f"max_import_fan_in={thresholds.max_import_fan_in}",
                )
            )

    _apply_baseline(violations, root)


def main() -> None:
    # ⚠️ Консоль Windows — cp1251, и один непечатаемый в ней символ в сообщении роняет
    # ВЕСЬ прогон с UnicodeEncodeError. Страж, падающий из-за собственного вывода,
    # неотличим от найденного нарушения. Сообщения тут по-русски, так что это вопрос
    # времени, а не гипотеза: уже случилось.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")

    args = parse_args()
    root = Path(args.root).resolve()
    critical_dirs = [Path(path).resolve() for path in args.critical]
    thresholds = Thresholds(
        max_lines_per_file=args.max_lines_per_file,
        max_function_length=args.max_function_length,
        max_cyclomatic_complexity=args.max_cyclomatic_complexity,
        max_import_fan_out=args.max_import_fan_out,
        max_import_fan_in=args.max_import_fan_in,
    )
    evaluate(root=root, critical_dirs=critical_dirs, thresholds=thresholds)


if __name__ == "__main__":
    main()
