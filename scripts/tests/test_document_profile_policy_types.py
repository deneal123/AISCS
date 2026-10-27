"""Offline parity must not accept policy-changing scalar coercions."""

import importlib.util
import shutil
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "check_document_profiles.py"
SPEC = importlib.util.spec_from_file_location("profile_policy_gate", PATH)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@pytest.mark.parametrize(
    ("field", "literal"),
    [
        ("version", "true"),
        ("version", "1.5"),
        ("version", '"2"'),
        ("max_pages", "true"),
        ("max_pages", "0"),
        ("max_pages", "-1"),
        ("max_pages", "8.5"),
        ("max_pages", '"8"'),
        ("bibliography_required", '"false"'),
        ("bibliography_required", "0"),
        ("bibliography_required", "1"),
        ("anonymize_supported", '"false"'),
        ("anonymize_supported", "0"),
        ("anonymize_supported", "1"),
    ],
)
def test_offline_gate_rejects_coerced_profile_policy(
    tmp_path, monkeypatch, capsys, field, literal
):
    root = tmp_path / "profiles"
    shutil.copytree(gate.PROFILE_ROOT, root)
    manifest = root / "generic_report/profile.toml"
    rows = [
        row
        for row in manifest.read_text(encoding="utf-8").splitlines()
        if not row.startswith(f"{field} =")
    ]
    manifest.write_text(
        "\n".join([*rows, f"{field} = {literal}", ""]), encoding="utf-8"
    )
    monkeypatch.setattr(gate, "PROFILE_ROOT", root)
    assert gate.main() == 1
    assert "profile field type invalid" in capsys.readouterr().err


def test_current_profile_contract_still_passes(capsys):
    assert gate.main() == 0
    assert "count=7" in capsys.readouterr().out
