"""Every ``service`` import in the repository resolves, historical scripts included.

Ruff cannot see a module that moved; this check imports each referenced module and
looks up each imported name, so dated migrations and scripts stay runnable.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("service", "scripts", "tests", "migrations")


def _package(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    return ".".join(parts if parts[-1] == "__init__" else parts[:-1]).removesuffix(".__init__")


def _absolute(node: ast.ImportFrom, path: Path) -> str:
    if not node.level:
        return node.module or ""
    base = _package(path).split(".")
    base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
    return ".".join(base + ([node.module] if node.module else []))


def unresolved() -> list[str]:
    errors = []
    files = [
        path
        for root in SCANNED
        for path in (ROOT / root).rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    for path in sorted(files):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            where = f"{path.relative_to(ROOT).as_posix()}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "service":
                        try:
                            importlib.import_module(alias.name)
                        except ImportError as exc:
                            errors.append(f"{where}: {alias.name} ({exc})")
            elif isinstance(node, ast.ImportFrom):
                module = _absolute(node, path)
                if module.split(".")[0] != "service":
                    continue
                try:
                    imported = importlib.import_module(module)
                except ImportError as exc:
                    errors.append(f"{where}: {module} ({exc})")
                    continue
                for alias in node.names:
                    if alias.name == "*" or hasattr(imported, alias.name):
                        continue
                    try:
                        importlib.import_module(f"{module}.{alias.name}")
                    except ImportError:
                        errors.append(f"{where}: {module}.{alias.name}")
    return errors


def main() -> int:
    sys.path.insert(0, str(ROOT))
    errors = unresolved()
    for error in errors:
        print("unresolved import:", error)
    print(f"service imports resolve: {not errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
