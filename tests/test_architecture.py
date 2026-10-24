"""Границы модулей проверяются без запуска HTTP и модели."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_does_not_import_acceptance_or_other_services():
    for source in (ROOT / "service").rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "acceptance" not in module, source
                assert not module.startswith(("agents.", "backend.", "workspace.")), source


def test_domain_and_application_do_not_own_http_or_processes():
    for layer in ("domain", "application"):
        for source in (ROOT / "service" / layer).rglob("*.py"):
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                modules = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                )
                assert not any(
                    module.startswith(("urllib", "http.", "subprocess", "socket"))
                    for module in modules
                ), source


def test_composition_refuses_unverified_model_before_binding(monkeypatch, capsys):
    from local_llm.service import main

    monkeypatch.setenv("LOCAL_LLM_API_KEY", "synthetic-key-" * 4)
    monkeypatch.setattr(main, "verified", lambda *_: False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Нельзя открывать HTTP до проверки весов")

    monkeypatch.setattr(main, "Gateway", forbidden)
    assert main.main() == 1
    assert capsys.readouterr().out.strip() == "local_llm_model_unverified"


def test_composition_injects_transport_and_named_runtime_fields(monkeypatch):
    from local_llm.service import main

    monkeypatch.setenv("LOCAL_LLM_API_KEY", "synthetic-key-" * 4)
    monkeypatch.setenv("LOCAL_LLM_MODEL_PATH", "/models/model.gguf")
    seen = {}
    server = object()

    def verified(path, model):
        seen["model_path"] = path
        return True

    def gateway(address, key, *, upstream):
        seen["address"] = address
        assert callable(upstream)
        return server

    def run(actual, command, child):
        assert actual is server
        assert child["LLAMA_API_KEY"] == "synthetic-key-" * 4
        assert command[command.index("--model") + 1] == str(seen["model_path"])
        return 7

    monkeypatch.setattr(main, "verified", verified)
    monkeypatch.setattr(main, "Gateway", gateway)
    monkeypatch.setattr(main, "run", run)
    assert main.main() == 7
