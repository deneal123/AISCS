"""Routes, editable-setting declarations and memory helpers have explicit boundaries."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "service"


@pytest.mark.parametrize(
    "package",
    [
        "services/chat/presentation/routers/chat_api/ide",
        "services/chat/presentation/routers/chat_api/workspace",
        "services/admin/application/settings",
        "services/analytics/application/memory",
    ],
)
def test_package_init_does_not_compose_routers_clients_or_mutable_registries(package):
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
    [
        ("services/chat/presentation/routers/chat_api", "ide_*.py"),
        ("services/chat/presentation/routers/chat_api", "workspace_*.py"),
        ("services/admin/application", "settings_*.py"),
        ("services/analytics/application", "memory_*.py"),
    ],
)
def test_families_do_not_return_as_flat_compatibility_modules(directory, pattern):
    assert not list((ROOT / directory).glob(pattern))
