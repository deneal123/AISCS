"""Compiler source identity must not be inferred from sidecar health alone."""

import hashlib
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "document_compiler_freshness",
    Path(__file__).parents[1] / "check_document_runtime_freshness.py",
)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def test_source_identity_is_covered_by_compiler_image_freshness():
    path = gate.COMPILER_FILES.get("source_identity.py")
    assert path == gate.ROOT / "workspace/service/domain/documents/source_identity.py"
    dockerfile = (gate.ROOT / "workspace/docker/document-runtime.Dockerfile").read_text()
    assert (
        "COPY service/domain/documents/source_identity.py "
        "/opt/document-runtime/source_identity.py"
    ) in dockerfile


def test_identity_covers_each_executable_source(tmp_path: Path, monkeypatch) -> None:
    runner = tmp_path / "runner.py"
    helper = tmp_path / "helper.py"
    runner.write_bytes(b"runner")
    helper.write_bytes(b"helper")
    monkeypatch.setattr(
        gate, "COMPILER_FILES", {"runner.py": runner, "helper.py": helper}
    )
    first = gate._compiler_source_digest()
    helper.write_bytes(b"changed")
    assert gate._compiler_source_digest() != first


def responses(
    monkeypatch,
    *,
    digest=None,
    failure=None,
    present=False,
    image="gpthub-document-runtime:latest",
):
    calls = []
    digest = digest or hashlib.sha256(b"fixture").hexdigest()

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if "exec" in args:
            return SimpleNamespace(returncode=0, stdout=image)
        if args[:2] == ["docker", "run"]:
            if failure:
                raise failure
            return SimpleNamespace(returncode=0, stdout=digest)
        if args[:2] == ["docker", "ps"]:
            return SimpleNamespace(
                returncode=0, stdout="owned-container" if present else ""
            )
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(gate.subprocess, "run", run)
    return calls, digest


def test_live_probe_is_local_isolated_and_removes_only_owned_container(
    monkeypatch,
) -> None:
    calls, digest = responses(monkeypatch)
    assert gate._live_compiler_digest() == digest
    run = next(args for args, _ in calls if args[:2] == ["docker", "run"])
    assert {"--pull=never", "--network=none", "--read-only", "--cap-drop=ALL"} <= set(
        run
    )
    assert not any(arg.startswith(("--volume", "--mount")) for arg in run)
    name = run[run.index("--name") + 1]
    assert name.startswith("gpthub-compiler-freshness-")
    assert any(args == ["docker", "rm", "-f", name] for args, _ in calls)
    assert all(kwargs.get("timeout") is not None for _, kwargs in calls)


@pytest.mark.parametrize(
    "failure",
    [OSError("PRIVATE_BODY"), subprocess.TimeoutExpired("PRIVATE_COMMAND", 30)],
)
def test_probe_failure_is_bounded_and_still_cleans(monkeypatch, failure) -> None:
    calls, _ = responses(monkeypatch, failure=failure)
    with pytest.raises(RuntimeError, match="^compiler_runtime_unavailable$") as caught:
        gate._live_compiler_digest()
    assert "PRIVATE" not in str(caught.value)
    assert any(args[:2] == ["docker", "rm"] for args, _ in calls)


def test_malformed_digest_is_not_accepted_or_echoed(monkeypatch) -> None:
    responses(monkeypatch, digest="PRIVATE_PROVIDER_BODY")
    with pytest.raises(RuntimeError, match="^compiler_runtime_unavailable$"):
        gate._live_compiler_digest()


def test_remaining_container_blocks_success(monkeypatch) -> None:
    responses(monkeypatch, present=True)
    with pytest.raises(RuntimeError, match="^compiler_cleanup_unavailable$"):
        gate._live_compiler_digest()


@pytest.mark.parametrize("image", ["--privileged", "unsafe image", "PRIVATE\nENV"])
def test_bad_image_configuration_never_runs_a_container(
    monkeypatch, image: str
) -> None:
    calls, _ = responses(monkeypatch, image=image)
    with pytest.raises(RuntimeError, match="^compiler_runtime_unavailable$"):
        gate._live_compiler_digest()
    assert not any(args[:2] == ["docker", "run"] for args, _ in calls)


def test_sidecar_health_does_not_hide_stale_compiler_source(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(gate.sys, "argv", ["gate", "--live"])
    monkeypatch.setattr(
        gate, "_source_identity", lambda *_args, **_kwargs: ("fixture", "digest")
    )
    monkeypatch.setattr(
        gate,
        "_live_health",
        lambda: {
            "agents": {"version": "fixture", "digest": "digest"},
            "workspace": {"version": "fixture", "digest": "digest"},
        },
    )
    monkeypatch.setattr(gate, "_compiler_source_digest", lambda: "new-source")
    monkeypatch.setattr(gate, "_live_compiler_digest", lambda: "old-image")
    assert gate.main() == 1
    assert "compiler_runtime_stale" in capsys.readouterr().err
