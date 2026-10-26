"""An observation failure must not hide an owned runtime or delete another."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probes import conn_esn_linux
from simctl import run_profile_controller

NAME = "aspa-sim-sim-013-linux-test"


def test_reconcile_container_after_uncertain_launch(monkeypatch):
    inspected = Mock(
        returncode=0,
        stdout=json.dumps(
            [
                {
                    "Name": "/" + NAME,
                    "Config": {"Labels": {"aspa.simulation.owner": "simctl"}},
                }
            ]
        ),
    )
    responses = iter(
        [
            inspected,
            Mock(returncode=0),
            Mock(returncode=1, stderr="Error: No such object: " + NAME),
        ]
    )
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(conn_esn_linux, "command", command)
    assert conn_esn_linux.remove_owned_container(NAME)["container_absent"]
    assert calls == [
        ["docker", "inspect", NAME],
        ["docker", "rm", "-f", NAME],
        ["docker", "inspect", NAME],
    ]


def test_daemon_error_is_not_proof_of_absence(monkeypatch):
    command = Mock(
        return_value=Mock(returncode=1, stderr="Cannot connect to Docker daemon")
    )
    monkeypatch.setattr(conn_esn_linux, "command", command)
    assert not conn_esn_linux.remove_owned_container(NAME)["container_absent"]
    command.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [
        "Error: No such object: x",
        "error: no such object: x",
        "No such container: x",
        "no such container: x",
    ],
)
def test_missing_runtime_observation_is_case_insensitive(monkeypatch, error):
    command = Mock(return_value=Mock(returncode=1, stderr=error))
    monkeypatch.setattr(conn_esn_linux, "command", command)
    assert conn_esn_linux.remove_owned_container(NAME)["container_absent"]
    command.assert_called_once()


def test_foreign_owner_is_never_removed(monkeypatch):
    command = Mock(
        return_value=Mock(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "Name": "/" + NAME,
                        "Config": {"Labels": {"aspa.simulation.owner": "foreign"}},
                    }
                ]
            ),
        )
    )
    monkeypatch.setattr(conn_esn_linux, "command", command)
    with pytest.raises(ValueError, match="ownership"):
        conn_esn_linux.remove_owned_container(NAME)
    command.assert_called_once()


def test_cli_dispatches_reviewed_controller(monkeypatch):
    run = Mock()
    monkeypatch.setattr(conn_esn_linux.subprocess, "run", run)
    run_profile_controller({"execution_controller": "conn_esn_linux"})
    args = run.call_args.args[0]
    assert Path(args[-1]).name == "conn_esn_linux.py"
    assert args[1:4] == ["-B", "-X", "utf8"]
    assert run.call_args.kwargs == {"check": True}


@pytest.mark.parametrize(
    "profile,resume",
    [
        ({"execution_controller": "foreign"}, None),
        ({"execution_controller": "conn_esn_linux"}, "old-run"),
    ],
)
def test_cli_rejects_unknown_controller_or_cleaned_resume(profile, resume):
    with pytest.raises(ValueError):
        run_profile_controller(profile, resume)


@pytest.mark.parametrize(
    "requested,result,expected",
    [
        (True, {"status": "partial", "phases": [{"status": "failed"}]}, True),
        (True, {"status": "partial", "phases": [{"reason": "timeout"}]}, False),
        (True, {"status": "passed"}, False),
        (True, {"status": "blocked"}, False),
        (False, {"status": "partial"}, False),
    ],
)
def test_only_explicit_non_timeout_partial_trial_may_be_retained(
    requested, result, expected
):
    assert conn_esn_linux.retain_for_diagnosis(requested, result) is expected
