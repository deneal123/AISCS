"""Worker and IDE packages preserve ownership boundaries without eager setup."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "service"
CHAT = "services/chat"
WORKER = f"{CHAT}/infrastructure/chat_worker"
PACKAGES = (
    f"{WORKER}/execution",
    f"{WORKER}/billing",
    f"{WORKER}/billing/reservation",
    f"{WORKER}/billing/usage",
    f"{WORKER}/results",
    f"{WORKER}/context",
    f"{WORKER}/continuation",
    f"{WORKER}/materialization",
    f"{CHAT}/domain/ide",
    f"{CHAT}/domain/ide/checkpoints",
    f"{CHAT}/persistence/ide",
    f"{CHAT}/persistence/ide/checkpoints",
    "infrastructure/ide",
    "infrastructure/ide/transports",
)


@pytest.mark.parametrize("package", PACKAGES)
def test_package_init_documents_the_boundary_without_creating_runtime_state(package):
    source = ROOT / package / "__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
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
        (f"{CHAT}/domain", "ide_*.py"),
        (f"{CHAT}/persistence", "ide_*.py"),
        ("infrastructure", "ide_*.py"),
        (WORKER, "execution_*.py"),
        (WORKER, "reservation*.py"),
        (WORKER, "usage_*.py"),
        (WORKER, "materialization_*.py"),
        (WORKER, "human_question_*.py"),
    ],
)
def test_flat_feature_families_do_not_return_as_compatibility_files(directory, pattern):
    assert not list((ROOT / directory).glob(pattern))


def test_worker_root_contains_only_explicit_composition_and_shared_run_contracts():
    assert {path.name for path in (ROOT / WORKER).glob("*.py")} == {
        "__init__.py",
        "engine_env.py",
        "factory.py",
        "phases.py",
        "run_contracts.py",
        "runtime_sync.py",
        "services.py",
        "task_runtime.py",
    }


def test_human_question_celery_identity_does_not_depend_on_moved_python_module():
    from service.services.chat.infrastructure.chat_worker.continuation.dispatch import (
        dispatch_human_question_children,
    )

    assert dispatch_human_question_children.name == (
        "service.infrastructure.messaging.tasks.dispatch_human_question_children"
    )
