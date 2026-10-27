"""Canonical-source migration must preserve, not weaken, the UI ownership gate."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "ui_contract_gate", ROOT / "scripts/check_frontend_ui_contract.py"
)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def test_current_project_uses_design_without_standalone_ux_contract():
    assert not (gate.FRONTEND / "UX-CONTRACT.md").exists()
    assert gate._failures() == []


@pytest.mark.parametrize("source", [None, "UX-CONTRACT.md", "../docs/PROJECT_TODO.md"])
def test_gate_rejects_missing_or_different_canonical_source(monkeypatch, source):
    original = Path.read_text
    config = gate.FRONTEND / "premium-ui.json"

    def read(path, *args, **kwargs):
        text = original(path, *args, **kwargs)
        if path == config:
            value = json.loads(text)
            if source is None:
                value.pop("canonicalMap", None)
            else:
                value["canonicalMap"] = source
            return json.dumps(value)
        return text

    monkeypatch.setattr(Path, "read_text", read)
    assert "premium:canonical_source" in gate._failures()


@pytest.mark.parametrize("capability", sorted(gate.CANONICAL_CAPABILITIES))
def test_design_is_not_a_substitute_for_missing_canonical_owner_row(
    monkeypatch, capability
):
    original = Path.read_text

    def read(path, *args, **kwargs):
        text = original(path, *args, **kwargs)
        if path == gate.FRONTEND / "DESIGN.md":
            text = text.replace(f"| {capability} |", f"| omitted-{capability} |")
        return text

    monkeypatch.setattr(Path, "read_text", read)
    assert f"contract:capability:{capability}" in gate._failures()


def test_canonical_header_is_still_required(monkeypatch):
    original = Path.read_text

    def read(path, *args, **kwargs):
        text = original(path, *args, **kwargs)
        if path == gate.FRONTEND / "DESIGN.md":
            text = text.replace(
                "| Capability | Canonical owner |", "| Capability | Other |"
            )
        return text

    monkeypatch.setattr(Path, "read_text", read)
    assert "contract:canonical_header" in gate._failures()
