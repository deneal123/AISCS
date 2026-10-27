"""Application packages expose responsibilities, not eager runtime composition."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "service/services/chat/application"


@pytest.mark.parametrize(
    "package",
    [
        "ide",
        "ide/checkpoints",
        "documents",
        "documents/audit",
        "documents/publication",
        "human_questions",
        "video_stt",
    ],
)
def test_application_package_documents_its_boundary_without_initialization(package):
    tree = ast.parse((ROOT / package / "__init__.py").read_text(encoding="utf-8"))
    assert ast.get_docstring(tree)
    assert all(
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for node in tree.body
    )


@pytest.mark.parametrize(
    "pattern", ["ide_*.py", "document_*.py", "pdf_*.py", "human_question*.py", "video_stt*.py"]
)
def test_application_families_do_not_return_as_flat_compatibility_modules(pattern):
    assert not list(ROOT.glob(pattern))


@pytest.mark.parametrize(
    "directory,pattern",
    [("ide", "checkpoint_*.py"), ("documents", "audit_*.py"), ("documents", "publication_*.py")],
)
def test_subsystems_have_dedicated_packages(directory, pattern):
    assert not list((ROOT / directory).glob(pattern))
