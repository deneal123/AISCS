"""Acceptance tooling must obey bounded isolation and verified ownership cleanup."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "document_smoke_boundaries", Path(__file__).parents[1] / "smoke_document_runtime.py"
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
CID = "a" * 64


def result(code=0, stdout=b""):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=b"")


def test_every_command_has_a_finite_deadline(monkeypatch):
    def invoke(*args, **kwargs):
        assert 0 < kwargs.get("timeout", 0) <= 90
        return result()

    monkeypatch.setattr(smoke.subprocess, "run", invoke)
    smoke._run("docker", "ps")


@pytest.mark.parametrize("error", ["timeout", "os"])
def test_process_failure_never_exposes_command_or_stderr(monkeypatch, error):
    def invoke(*_, **__):
        if error == "timeout":
            raise subprocess.TimeoutExpired(
                ["PRIVATE_COMMAND"], 1, stderr=b"PRIVATE_BODY"
            )
        raise OSError("PRIVATE_BODY")

    monkeypatch.setattr(smoke.subprocess, "run", invoke)
    with pytest.raises(RuntimeError) as raised:
        smoke._run("docker", "ps")
    assert str(raised.value) in {"process_timeout", "process_unavailable"}
    assert raised.value.__cause__ is None


def setup(
    monkeypatch,
    *,
    lost_ack=False,
    malformed_id=False,
    foreign=False,
    cleanup_failure=False,
):
    calls = []
    state = {"present": False, "name": "", "removed": False}
    monkeypatch.setattr(
        smoke, "_source_archive", lambda *_, **__: (b"synthetic", {"engine": "xelatex"})
    )

    def invoke(*args, **kwargs):
        calls.append((args, kwargs))
        if "create" in args:
            state["present"] = True
            state["name"] = args[args.index("--name") + 1]
            if lost_ack:
                raise RuntimeError("process_timeout")
            return result(stdout=b"PRIVATE_ID" if malformed_id else CID.encode())
        if "ps" in args:
            return result(stdout=(CID + "\n").encode() if state["present"] else b"")
        if "inspect" in args:
            return result(
                stdout=json.dumps(
                    {
                        "id": CID,
                        "name": "/" + state["name"],
                        "owner": "foreign" if foreign else state["name"],
                    }
                ).encode()
            )
        if "rm" in args:
            if cleanup_failure:
                return result(1)
            state["present"] = False
            state["removed"] = True
            return result()
        if "start" in args:
            return result(1)
        raise AssertionError("unexpected_fixture_command")

    monkeypatch.setattr(smoke, "_run", invoke)
    return calls, state


def create_args(calls):
    return next(args for args, _ in calls if "create" in args)


def test_container_has_fixed_resources_and_never_pulls_image(monkeypatch):
    calls, state = setup(monkeypatch)
    with pytest.raises(RuntimeError):
        smoke._smoke_profile(
            "gpthub-document-runtime:latest", "generic_document", publication=False
        )
    args = create_args(calls)
    for flag in ("--memory", "--memory-swap", "--cpus", "--pids-limit"):
        assert flag in args
    assert "--pull=never" in args or (
        "--pull" in args and args[args.index("--pull") + 1] == "never"
    )
    assert "--label" in args
    assert state["removed"]


def test_lost_create_ack_still_cleans_exact_owned_name(monkeypatch):
    calls, state = setup(monkeypatch, lost_ack=True)
    with pytest.raises(RuntimeError):
        smoke._smoke_profile(
            "gpthub-document-runtime:latest", "generic_document", publication=False
        )
    assert state["removed"] and not state["present"]
    assert any("inspect" in args for args, _ in calls)


def test_malformed_create_id_is_never_used_as_docker_target(monkeypatch):
    calls, state = setup(monkeypatch, malformed_id=True)
    with pytest.raises(RuntimeError):
        smoke._smoke_profile(
            "gpthub-document-runtime:latest", "generic_document", publication=False
        )
    assert not any("PRIVATE_ID" in args for args, _ in calls)
    assert state["removed"]


def test_foreign_label_prevents_removal(monkeypatch):
    calls, state = setup(monkeypatch, foreign=True)
    with pytest.raises(RuntimeError, match="^cleanup_unconfirmed$"):
        smoke._smoke_profile(
            "gpthub-document-runtime:latest", "generic_document", publication=False
        )
    assert not state["removed"]
    assert not any("rm" in args for args, _ in calls)


def test_cleanup_ack_is_not_equivalent_to_proven_absence(monkeypatch):
    calls, state = setup(monkeypatch, cleanup_failure=True)
    with pytest.raises(RuntimeError, match="^cleanup_unconfirmed$"):
        smoke._smoke_profile(
            "gpthub-document-runtime:latest", "generic_document", publication=False
        )
    assert state["present"]
    assert sum("ps" in args for args, _ in calls) >= 2


def test_cli_does_not_print_unknown_exception_text(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["smoke"])

    def failure(*_, **__):
        raise OSError("PRIVATE_CREDENTIAL_MARKER")

    monkeypatch.setattr(smoke, "_smoke_profile", failure)
    assert smoke.main() == 1
    output = capsys.readouterr()
    assert "PRIVATE" not in output.out + output.err
    assert "code=smoke_failed" in output.out
