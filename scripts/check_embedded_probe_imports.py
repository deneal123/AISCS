"""Check local imports in opt-in probe sources without importing or executing them.

Ordinary pytest collection does not resolve imports inside quoted remote Python.
Only repository test probes/fixtures are scanned, with their owning service root.
This is a source check, never SQL, Docker or provider acceptance.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# These backend-owned acceptance files deliberately execute selected snippets in agents.
# Bind by source variable, not by whichever service happens to contain a matching module.
SNIPPET_PROJECTS = {
    ("backend", "tests/test_document_audit_recovery_rpc_live.py", "_SEED"): "agents",
    ("backend", "tests/test_document_audit_recovery_rpc_live.py", "_CLEAN_REDIS"): "agents",
    ("backend", "tests/test_gigachat_literal_audit_delivery_live.py", "_BUILD"): "agents",
}


def _declared_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            return  # Function/class locals are not package exports.
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return names


def unresolved_imports(source: str, project: Path) -> set[str]:
    """Validate module existence and package exports; never import live dependencies."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()  # The probe's own compile guard owns non-Python/template syntax.
    missing: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("service."):
                    path = project.joinpath(*alias.name.split("."))
                    if not path.with_suffix(".py").is_file() and not path.is_dir():
                        missing.add(alias.name)
            continue
        if not isinstance(node, ast.ImportFrom) or node.level:
            continue
        target = node.module or ""
        if not target.startswith("service."):
            continue
        path = project.joinpath(*target.split("."))
        if path.with_suffix(".py").is_file():
            continue  # Ordinary module symbols are covered by runtime unit tests.
        if not path.is_dir():
            missing.add(target)
            continue
        initializer = path / "__init__.py"
        exports = (
            _declared_names(ast.parse(initializer.read_text("utf-8")))
            if initializer.is_file()
            else set()
        )
        if "__getattr__" in exports:
            continue  # A dynamic facade cannot be validated without executing it.
        for alias in node.names:
            child = path / alias.name
            if (
                alias.name != "*"
                and alias.name not in exports
                and not (child.with_suffix(".py").is_file() or child.is_dir())
            ):
                missing.add(f"{target}.{alias.name}")
    return missing


def probe_failures(project: Path) -> list[tuple[Path, int, str]]:
    failures = []
    for path in sorted((project / "tests").rglob("*.py")):
        if not any(word in path.name for word in ("live", "probe", "fixture")):
            continue
        tree = ast.parse(path.read_text("utf-8"))
        names = {
            id(node.value): node.targets[0].id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        }
        sources = [(1, path.read_text("utf-8"), "")]
        sources.extend(
            (node.lineno, node.value, names.get(id(node), ""))
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "\n" in node.value
            and ("from service." in node.value or "import service." in node.value)
        )
        for line, source, variable in sources:
            owner = SNIPPET_PROJECTS.get(
                (project.name, path.relative_to(project).as_posix(), variable)
            )
            target = project.parent / owner if owner else project
            failures.extend(
                (path, line, name) for name in sorted(unresolved_imports(source, target))
            )
    return failures


def cli_failures(source: str, project: Path) -> set[str]:
    """Resolve agent CLI references in shell recipes; never launch the recipes."""
    commands = re.findall(r"\bpython(?:3)?\s+-m\s+(service\.presentation\.cli\.[\w.]+)", source)
    return {
        missing for name in commands for missing in unresolved_imports(f"import {name}", project)
    }


def main() -> int:
    for name in ("agents", "backend"):
        if not (ROOT / name / "tests").is_dir():
            print(f"probe sources unavailable: {name}")
            return 1
    failures = [item for name in ("agents", "backend") for item in probe_failures(ROOT / name)]
    makefile = ROOT / "Makefile"
    if not makefile.is_file():
        print("CLI recipe sources unavailable")
        return 1
    failures.extend(
        (makefile, 1, name)
        for name in sorted(cli_failures(makefile.read_text("utf-8"), ROOT / "agents"))
    )
    for path, line, name in failures:
        print(f"unresolved probe import: {path.relative_to(ROOT)}:{line}: {name}")
    if failures:
        return 1
    print("embedded probe imports and agent CLI recipes resolve: source-only; nothing executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
