from __future__ import annotations

import argparse
import ast
import json
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

    if failures:
        failures.append(
            f"\nЕсли рост осознан — обновите {BASELINE_FILE.name}, "
            "но это должно быть видно в ревью."
        )
        raise QualityError("\n".join(sorted(failures)))

    current = {key for key, _, _ in violations}
    fixed = sorted(set(baseline) - current)
    if fixed:
        print("Долг погашен, уберите из complexity_baseline.json:")
        for key in fixed:
            print(f"  {key}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="service")
    parser.add_argument("--critical", nargs="+", default=["service/services", "service/agents"])
    parser.add_argument("--max-lines-per-file", type=int, default=750)
    parser.add_argument("--max-function-length", type=int, default=250)
    parser.add_argument("--max-cyclomatic-complexity", type=int, default=70)
    parser.add_argument("--max-import-fan-out", type=int, default=120)
    parser.add_argument("--max-import-fan-in", type=int, default=160)
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
