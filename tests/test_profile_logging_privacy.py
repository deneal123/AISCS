"""Regression guard for credentials and profile PII in diagnostics."""

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROFILE_MODULES = (
    BACKEND_ROOT / "service/services/profile/application/auth_service.py",
    BACKEND_ROOT / "service/services/profile/application/profile_service.py",
    BACKEND_ROOT / "service/services/profile/persistence/profile_repository.py",
)
SENSITIVE_NAMES = {
    "email",
    "normalized_email",
    "password",
    "password_hash",
    "profile",
    "user",
    "user_id",
    "user_profile",
}


def _logger_calls(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if isinstance(owner, ast.Name) and owner.id == "logger":
            calls.append(node)
    return calls


def _referenced_names(call: ast.Call) -> set[str]:
    names: set[str] = set()
    for argument in (*call.args, *(keyword.value for keyword in call.keywords)):
        names.update(node.id for node in ast.walk(argument) if isinstance(node, ast.Name))
    return names


def test_profile_diagnostics_do_not_serialize_sensitive_values() -> None:
    violations: list[str] = []
    for module in PROFILE_MODULES:
        source = module.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module))
        for call in _logger_calls(tree):
            sensitive = sorted(_referenced_names(call) & SENSITIVE_NAMES)
            if sensitive:
                violations.append(f"{module}:{call.lineno}: {', '.join(sensitive)}")

    assert violations == [], "profile diagnostics expose sensitive values: " + "; ".join(violations)
