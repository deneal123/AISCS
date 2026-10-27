"""Scanning owns its metrics; Redis helpers reuse the existing cache boundary."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "service"


@pytest.mark.parametrize("package", ["services/files/application/scanning", "infrastructure/cache"])
def test_package_boundary_does_not_create_scanner_metrics_or_redis_clients(package):
    tree = ast.parse((ROOT / package / "__init__.py").read_text(encoding="utf-8"))
    assert ast.get_docstring(tree)
    assert all(
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for node in tree.body
    )


@pytest.mark.parametrize(
    "directory,pattern",
    [("services/files/application", "file_scan*.py"), ("infrastructure/cache", "redis_*.py")],
)
def test_old_scanning_and_redis_paths_do_not_become_compatibility_wrappers(directory, pattern):
    assert not list((ROOT / directory).glob(pattern))
