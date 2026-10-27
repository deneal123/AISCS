"""Harness SQL and worker composition have separate, non-eager packages."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "service/services/chat"


@pytest.mark.parametrize("directory", ["persistence", "infrastructure/chat_worker"])
def test_harness_implementations_are_grouped_without_flat_compatibility_files(directory):
    parent = ROOT / directory
    assert not list(parent.glob("harness_*.py"))
    assert not (parent / "harness.py").exists()
    tree = ast.parse((parent / "harness/__init__.py").read_text(encoding="utf-8"))
    assert ast.get_docstring(tree)
    assert all(
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for node in tree.body
    )
