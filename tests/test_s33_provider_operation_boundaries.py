from __future__ import annotations

import ast
from pathlib import Path

import pytest

from service.domain.client.provider_operations import ProviderOperation

_OPERATION_MODULES = (
    "service/domain/base.py",
    "service/domain/media.py",
    "service/domain/runners/sdk_run.py",
    "service/domain/subagents/image_generation.py",
    "service/domain/tools/image_gen.py",
    "service/domain/tools/pptx.py",
    "service/domain/tools/vector_store.py",
)
_FORBIDDEN_CALLS = {
    "get_active_provider",
    "get_openai_client",
    "get_provider_module",
    "list_available_models",
}


@pytest.mark.parametrize("relative_path", _OPERATION_MODULES)
def test_model_operation_module_does_not_read_mutable_provider_globals(
    relative_path: str,
) -> None:
    root = Path(__file__).parents[1]
    tree = ast.parse((root / relative_path).read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "OPENAI_CLIENT":
            violations.append(f"OPENAI_CLIENT:{node.lineno}")
        if not isinstance(node, ast.Call):
            continue
        called = node.func.id if isinstance(node.func, ast.Name) else None
        if called in _FORBIDDEN_CALLS:
            violations.append(f"{called}:{node.lineno}")
    assert violations == [], f"mutable provider access outside compatibility boundary: {violations}"


def test_every_provider_operation_has_positive_capability_evidence() -> None:
    assert {operation.value for operation in ProviderOperation} == {
        "chat",
        "tool_chat",
        "vision_input",
        "image_output",
        "embeddings",
        "transcription",
    }
    assert all(operation.required_capabilities for operation in ProviderOperation)
