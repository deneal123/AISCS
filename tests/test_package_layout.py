"""Keep cohesive feature packages explicit and their initialization side-effect free."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "service"
PACKAGES = (
    "application/harness",
    "application/admission",
    "application/processing",
    "application/human_questions",
    "infrastructure/harness",
    "infrastructure/document_audit",
    "domain/runners/harness",
    "domain/execution",
    "domain/usage",
    "domain/runners/chat",
    "domain/runners/sdk",
    "domain/runners/ide",
    "domain/tools/workspace",
    "domain/tools/ide",
    "domain/tools/search",
    "domain/client/models",
    "domain/client/providers/management",
    "domain/client/providers/gigachat",
    "domain/client/providers/openai",
    "domain/client/providers/transports",
    "domain/capabilities/tools",
    "domain/documents/authoring",
    "domain/documents/evidence",
    "domain/documents/semantic",
    "domain/documents/skills",
    "domain/pipeline/context",
    "domain/routing/auto",
    "domain/workflows/research",
    "presentation/cli/gigachat",
)


@pytest.mark.parametrize("package", PACKAGES)
def test_feature_package_has_no_eager_runtime_initialization(package):
    path = ROOT / package / "__init__.py"
    assert path.is_file()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert ast.get_docstring(tree), f"{package} must explain its responsibility"
    assert all(
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for node in tree.body
    )


@pytest.mark.parametrize(
    "directory,pattern",
    [
        ("infrastructure", "harness_*.py"),
        ("infrastructure", "document_audit_*.py"),
        ("application", "harness_*.py"),
        ("application", "processor*.py"),
        ("application", "human_question_*.py"),
        ("application", "document_*.py"),
        ("application", "ide_*.py"),
        ("domain/runners", "harness_*.py"),
        ("domain/runners", "chat_*.py"),
        ("domain/runners", "sdk_*.py"),
        ("domain/runners", "ide_*.py"),
        ("domain/tools", "workspace_*.py"),
        ("domain/tools", "ide_*.py"),
        ("domain/tools", "web_search*.py"),
        ("domain/tools", "search_parsers.py"),
        ("domain/tools", "found_sources.py"),
        ("domain/client", "provider_*.py"),
        ("domain/client", "model_*.py"),
        ("domain/client/providers", "gigachat*.py"),
        ("domain/client/providers", "openai*.py"),
        ("domain/capabilities", "tool_*.py"),
        ("domain/documents", "authoring*.py"),
        ("domain/documents", "evidence*.py"),
        ("domain/documents", "skill*.py"),
        ("domain/documents", "profile_contract.py"),
        ("domain/documents", "draft.py"),
        ("domain/documents", "editor.py"),
        ("domain/documents", "outline.py"),
        ("domain/documents", "rendering.py"),
        ("domain/documents", "section_parser.py"),
        ("domain/documents", "source_mentions.py"),
        ("domain/documents", "registered_sources.py"),
        ("domain/pipeline", "context_*.py"),
        ("domain", "usage_*.py"),
        ("domain", "legacy_usage.py"),
        ("domain", "run_context.py"),
        ("domain/routing", "auto_*.py"),
        ("domain/workflows", "research_*.py"),
        ("presentation/cli", "gigachat_*.py"),
    ],
)
def test_feature_family_does_not_return_as_flat_files_or_compatibility_wrappers(directory, pattern):
    assert not list((ROOT / directory).glob(pattern))


def test_document_runtime_identity_covers_real_paths_after_package_moves():
    from service.domain.documents.runtime_digest import (
        DOCUMENT_RUNTIME_DIGEST,
        compute_document_runtime_digest,
    )

    assert DOCUMENT_RUNTIME_DIGEST == compute_document_runtime_digest()


def test_tool_runtime_has_no_redundant_flat_execution_facade():
    assert not (ROOT / "domain/runners/tool_execution.py").exists()
