"""The import check reports moved modules and missing names in any scanned tree."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _check_imports():
    spec = importlib.util.spec_from_file_location(
        "check_imports", ROOT / "scripts" / "check_imports.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_service_imports_resolve() -> None:
    assert _check_imports().unresolved() == []


def test_moved_module_and_missing_name_are_reported(tmp_path, monkeypatch) -> None:
    module = _check_imports()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "historical.py").write_text(
        "from service.pipeline import atomic_write_json\n"
        "from service.common.jsonio import missing_helper\n"
        "from service.common.jsonio import load_json\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SCANNED", ("scripts",))
    errors = module.unresolved()
    assert len(errors) == 2
    assert "service.pipeline" in errors[0]
    assert errors[1].endswith("service.common.jsonio.missing_helper")
