"""Static architecture gate for ledger-only production execution."""

from __future__ import annotations

import ast
from pathlib import Path

SERVICE = Path(__file__).parents[1] / "service"


def _production_sources() -> list[Path]:
    return sorted(SERVICE.rglob("*.py"))


def test_mutable_usage_bridge_is_isolated() -> None:
    allowed_usage_out = {"domain/legacy_usage.py"}
    allowed_legacy_import = {"domain/client/calls/legacy_stream.py"}
    usage_out_offenders: list[str] = []
    legacy_import_offenders: list[str] = []

    for path in _production_sources():
        relative = path.relative_to(SERVICE).as_posix()
        source = path.read_text(encoding="utf-8")
        if "usage_out" in source and relative not in allowed_usage_out:
            usage_out_offenders.append(relative)
        if "legacy_usage" in source and relative not in allowed_legacy_import | allowed_usage_out:
            legacy_import_offenders.append(relative)

    assert usage_out_offenders == []
    assert legacy_import_offenders == []


def test_removed_mutable_usage_names_do_not_return() -> None:
    forbidden = ("usage_acc", "usage_projection", "_merge_usage")
    offenders: list[str] = []
    for path in _production_sources():
        source = path.read_text(encoding="utf-8")
        if any(name in source for name in forbidden):
            offenders.append(path.relative_to(SERVICE).as_posix())
    assert offenders == []


def test_production_does_not_construct_detached_run_context() -> None:
    offenders: list[str] = []
    for path in _production_sources():
        relative = path.relative_to(SERVICE).as_posix()
        if relative == "domain/run_context.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if isinstance(function, ast.Name) and function.id == "RunExecutionContext":
                offenders.append(f"{relative}:{node.lineno}")
            elif isinstance(function, ast.Attribute) and function.attr == "RunExecutionContext":
                offenders.append(f"{relative}:{node.lineno}")
    assert offenders == []


def test_provider_session_is_constructed_only_by_run_context() -> None:
    offenders: list[str] = []
    for path in _production_sources():
        relative = path.relative_to(SERVICE).as_posix()
        if relative == "domain/run_context.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else ""
            )
            if name in {"RunExecutionContext", "ProviderRunSession", "UsageLedger"}:
                offenders.append(f"{relative}:{node.lineno}:{name}")
    assert offenders == []


def test_production_entrypoint_owns_exactly_one_scoped_run() -> None:
    entrypoint = (SERVICE / "application" / "agent_execution_service.py").read_text(
        encoding="utf-8"
    )
    assert entrypoint.count("use_run_execution(") == 1
    assert "ReplyAssembler(run_execution.usage)" in entrypoint
