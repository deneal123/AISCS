"""Compiler smoke must exercise the profile's actual engine, never a fixed shortcut."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("engine", ["pdflatex", "xelatex", "lualatex"])
def test_smoke_passes_exact_profile_engine(monkeypatch, engine):
    path = Path(__file__).resolve().parents[2] / "scripts" / "smoke_document_runtime.py"
    if not path.exists():
        pytest.skip("root compiler smoke belongs to the superproject")
    spec = importlib.util.spec_from_file_location("engine_smoke", path)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    monkeypatch.setattr(smoke, "_source_archive", lambda *a, **k: (b"fixture", {"engine": engine}))
    observed = []
    fixture_id = "c" * 64
    state = {"name": None, "exists": False}

    def run(*args, **kwargs):
        payload = b""
        if args[1] == "create":
            state.update(name=args[args.index("--name") + 1], exists=True)
            payload = fixture_id.encode()
        elif args[1] == "ps":
            payload = fixture_id.encode() if state["exists"] else b""
        elif args[1] == "inspect":
            payload = json.dumps(
                {
                    "id": fixture_id,
                    "name": "/" + state["name"],
                    "owner": state["name"],
                }
            ).encode()
        elif args[1] == "rm":
            assert args[-1] == fixture_id
            state["exists"] = False
        if "--engine" in args:
            observed.append(args[args.index("--engine") + 1])
            return subprocess.CompletedProcess(args, 1, b"", b"")
        return subprocess.CompletedProcess(args, 0, payload, b"")

    monkeypatch.setattr(smoke, "_run", run)
    with pytest.raises(RuntimeError, match="^compile_failed$"):
        smoke._smoke_profile("fixture-image", "fixture-profile", publication=False)
    assert observed == [engine]
    assert not state["exists"]


def test_aaai_style_scaffold_uses_embedded_outline_font():
    root = Path(__file__).resolve().parents[2]
    profile = root / "workspace/service/domain/documents/profile_data/aaai_conference/main.tex"
    if not profile.exists():
        pytest.skip("profile belongs to the workspace submodule")
    source = profile.read_text("utf-8")
    assert r"\usepackage[T1]{fontenc}" in source
    assert r"\usepackage{lmodern}" in source
