"""PID reuse cannot redirect Stop between identity validation and signal delivery."""

import io
import os
import runpy
import signal
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("observed,signals", [("old", 0), ("expected", 1)])
def test_stop_uses_pidfd_and_refuses_reused_namespace_pid(monkeypatch, observed, signals):
    opened, killed, closed = Mock(return_value=77), Mock(), Mock()
    monkeypatch.setattr(os, "pidfd_open", opened, raising=False)
    monkeypatch.setattr(os, "close", closed)
    monkeypatch.setattr(signal, "pidfd_send_signal", killed, raising=False)
    monkeypatch.setattr("sys.argv", ["stop.py", "123", "expected"])
    fields = ["0"] * 20
    fields[19] = observed
    real_open = open

    def source(path, *args, **kwargs):
        if str(path) == "/proc/123/stat":
            return io.StringIO("123 (supervisor) " + " ".join(fields))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", source)
    script = Path(__file__).parents[1] / "docker/harness/stop.py"
    if signals:
        runpy.run_path(str(script))
        killed.assert_called_once_with(77, signal.SIGTERM)
    else:
        with pytest.raises(SystemExit) as error:
            runpy.run_path(str(script))
        assert error.value.code == 3
        killed.assert_not_called()
    opened.assert_called_once_with(123)
    closed.assert_called_once_with(77)
