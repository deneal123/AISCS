"""Live probe reports bounded failures without forwarding container diagnostics."""

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "sidecar_proxy_smoke", Path(__file__).parents[1] / "smoke_sidecar_proxy.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(returncode=1, stdout="PRIVATE_EXCEPTION_BODY"),
        SimpleNamespace(returncode=0, stdout='{"status":"passed"}'),
        SimpleNamespace(returncode=0, stdout="[]"),
        SimpleNamespace(returncode=0, stdout="null"),
    ],
)
def test_invalid_or_incomplete_probe_is_bounded(monkeypatch, capsys, result):
    monkeypatch.setattr("sys.argv", ["smoke", "--live"])
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **kw: result)
    assert probe.main() == 1
    assert capsys.readouterr().out == '{"service": "agents", "status": "failed"}\n'


def test_process_timeout_does_not_print_private_command(monkeypatch, capsys):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("PRIVATE_COMMAND", 20, stderr="PRIVATE_BODY")

    monkeypatch.setattr("sys.argv", ["smoke", "--live"])
    monkeypatch.setattr(probe.subprocess, "run", timeout)
    assert probe.main() == 1
    assert "PRIVATE" not in capsys.readouterr().out


def test_no_implicit_live_execution(monkeypatch):
    monkeypatch.setattr("sys.argv", ["smoke"])
    with pytest.raises(SystemExit) as error:
        probe.main()
    assert error.value.code == 2
