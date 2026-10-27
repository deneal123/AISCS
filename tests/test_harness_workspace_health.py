"""Краткий сбой наблюдения не перезапускает проверяемый workspace-процесс."""

import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.harness.live import host


@pytest.mark.parametrize("failure", [RuntimeError(), subprocess.TimeoutExpired("docker", 3)])
def test_health_retries_observation_of_the_same_live_process(monkeypatch, failure):
    process = SimpleNamespace(poll=Mock(return_value=None))
    docker = Mock(side_effect=[failure, ""])
    monkeypatch.setattr(host, "docker", docker)
    monkeypatch.setattr(host.time, "sleep", Mock())
    host.wait_workspace(process, "workspace-fixture")
    assert process.poll.call_count == 2
    assert docker.call_args_list[0] == docker.call_args_list[1]
    assert docker.call_args.args[:2] == ("exec", "workspace-fixture")


def test_health_observation_does_not_extend_its_deadline(monkeypatch):
    monkeypatch.setattr(host, "docker", Mock(side_effect=subprocess.TimeoutExpired("docker", 3)))
    monkeypatch.setattr(host.time, "monotonic", Mock(side_effect=[0, 31]))
    with pytest.raises(RuntimeError, match="acceptance_workspace_not_ready"):
        host.wait_workspace(SimpleNamespace(poll=lambda: None), "workspace-fixture")


def test_terminal_process_is_not_restarted_or_observed_as_healthy(monkeypatch):
    docker = Mock()
    monkeypatch.setattr(host, "docker", docker)
    with pytest.raises(AssertionError, match="acceptance_workspace_stopped"):
        host.wait_workspace(SimpleNamespace(poll=lambda: 1), "workspace-fixture")
    docker.assert_not_called()
