"""Private journals and audit transport remain separate from public application composition."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "service"
PACKAGES = (
    "services/chat/domain/human_questions",
    "services/chat/domain/confirmation",
    "services/chat/domain/documents",
    "services/chat/persistence/human_questions",
    "services/chat/persistence/documents",
    "services/chat/persistence/documents/audit",
    "services/chat/persistence/workflows",
    "infrastructure/agents_client/document_audit",
)


@pytest.mark.parametrize("package", PACKAGES)
def test_journal_package_has_no_eager_database_provider_or_task_setup(package):
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
        ("services/chat/domain", "human_question*.py"),
        ("services/chat/domain", "confirmation_*.py"),
        ("services/chat/persistence", "human_question*.py"),
        ("services/chat/persistence", "document_*.py"),
        ("services/chat/persistence", "workflow_catalog*.py"),
        ("infrastructure/agents_client", "document_audit*.py"),
    ],
)
def test_journal_families_do_not_return_as_flat_compatibility_modules(directory, pattern):
    assert not list((ROOT / directory).glob(pattern))
