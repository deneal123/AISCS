"""Probe import validation stays static and rejects stranded moved modules."""

import importlib.util
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "check_embedded_probe_imports.py"
spec = importlib.util.spec_from_file_location("embedded_probe_imports", PATH)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def test_missing_old_submodule_inside_existing_namespace_is_rejected(tmp_path):
    parent = tmp_path / "service/application"
    parent.mkdir(parents=True)
    assert gate.unresolved_imports("from service.application import memory_service", tmp_path) == {
        "service.application.memory_service"
    }


def test_valid_alias_and_reexport_are_checked_without_executing_modules(tmp_path):
    package = tmp_path / "service/application/memory"
    package.mkdir(parents=True)
    (package / "service.py").write_text("raise RuntimeError('must not execute')\n")
    (package / "__init__.py").write_text("from .service import PublicService\n")
    source = "from service.application.memory import service as memory_service, PublicService"
    assert gate.unresolved_imports(source, tmp_path) == set()


def test_probe_scan_checks_quoted_code_but_does_not_run_it(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_example_live.py").write_text(
        "PROBE = '''\nfrom service.missing import old_module\nraise SystemExit(9)\n'''\n"
    )
    failures = gate.probe_failures(tmp_path)
    assert len(failures) == 1 and failures[0][2] == "service.missing"


def test_missing_direct_module_is_rejected(tmp_path):
    assert gate.unresolved_imports("from service.absent import Item", tmp_path) == {
        "service.absent"
    }


def test_function_local_name_does_not_make_a_missing_package_export_valid(tmp_path):
    package = tmp_path / "service/application"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("def helper():\n    old_module = 1\n")
    assert gate.unresolved_imports("from service.application import old_module", tmp_path) == {
        "service.application.old_module"
    }


def test_missing_checkout_is_not_reported_as_an_empty_success(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    assert gate.main() == 1
    assert "probe sources unavailable" in capsys.readouterr().out


def test_makefile_cli_module_is_checked_without_running_a_paid_probe(tmp_path):
    cli = tmp_path / "service/presentation/cli/gigachat"
    cli.mkdir(parents=True)
    (cli / "tools.py").write_text("raise RuntimeError('must never execute')\n")
    recipes = (
        "python -m service.presentation.cli.gigachat.tools\n"
        "python -m service.presentation.cli.gigachat_tools_smoke\n"
    )
    assert gate.cli_failures(recipes, tmp_path) == {"service.presentation.cli.gigachat_tools_smoke"}


def test_cross_service_source_owner_is_explicit_not_fallback_search(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    tests = backend / "tests"
    tests.mkdir(parents=True)
    service = tmp_path / "agents/service"
    service.mkdir(parents=True)
    (service / "remote.py").write_text("raise RuntimeError('not executed')\n")
    (tests / "test_remote_live.py").write_text(
        "REMOTE = '''\nfrom service.remote import Item\n'''\n"
    )
    assert gate.probe_failures(backend)
    monkeypatch.setattr(
        gate,
        "SNIPPET_PROJECTS",
        {
            ("backend", "tests/test_remote_live.py", "REMOTE"): "agents",
        },
    )
    assert gate.probe_failures(backend) == []
