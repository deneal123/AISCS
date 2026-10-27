"""Acceptance runner must not certify absent cards or expose browser capabilities."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "library_browser_smoke", ROOT / "scripts/smoke_library_download_browser.py"
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
FIXTURE_PROBE = "owner_email='s37-e2e-391e5206659a3654@example.com'"


@pytest.fixture(autouse=True)
def default_surface(monkeypatch):
    monkeypatch.delenv("S37_LIBRARY_DOWNLOAD_SURFACE", raising=False)


def test_browser_smoke_requires_opt_in(monkeypatch, capsys):
    monkeypatch.delenv("S37_LIVE_LIBRARY_DOWNLOAD_BROWSER", raising=False)
    assert smoke.main() == 2
    assert json.loads(capsys.readouterr().out)["stage"] == "opt_in_required"


@pytest.mark.parametrize(
    ("stats", "code"),
    [
        ({"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0}, 0),
        ({"expected": 0, "unexpected": 0, "skipped": 2, "flaky": 0}, 1),
        ({"expected": 1, "unexpected": 1, "skipped": 0, "flaky": 0}, 1),
        ({"expected": 2, "unexpected": 0, "skipped": 0, "flaky": True}, 1),
    ],
)
def test_browser_smoke_requires_two_real_passes_without_sensitive_output(
    monkeypatch, capsys, stats, code
):
    marker = "PRIVATE_BROWSER_CAPABILITY"
    monkeypatch.setenv("S37_LIVE_LIBRARY_DOWNLOAD_BROWSER", "1")
    monkeypatch.setattr(smoke.runpy, "run_path", lambda _: {"_BROWSER_PROBE": FIXTURE_PROBE})
    replies = iter(
        [
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"token": marker, "files": [{"id": "one"}, {"id": "two"}]}),
            ),
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"stats": stats, "errors": [{"message": marker}]}),
            ),
        ]
    )
    monkeypatch.setattr(smoke.subprocess, "run", lambda *a, **kw: next(replies))
    assert smoke.main() == code
    output = capsys.readouterr().out
    assert marker not in output
    assert json.loads(output)["status"] == ("passed" if code == 0 else "failed")


def test_missing_retained_cards_never_launch_browser(monkeypatch, capsys):
    monkeypatch.setenv("S37_LIVE_LIBRARY_DOWNLOAD_BROWSER", "1")
    monkeypatch.setattr(smoke.runpy, "run_path", lambda _: {"_BROWSER_PROBE": FIXTURE_PROBE})
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1, stdout='{"stage":"delivered_files"}')

    monkeypatch.setattr(smoke.subprocess, "run", run)
    assert smoke.main() == 2
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().out)["stage"] == "retained_card_fixture_unavailable"


def test_work_download_uses_owned_library_fixture_without_fabricating_chat(monkeypatch, capsys):
    monkeypatch.setenv("S37_LIVE_LIBRARY_DOWNLOAD_BROWSER", "1")
    monkeypatch.setenv("S37_LIBRARY_DOWNLOAD_SURFACE", "work")
    monkeypatch.setattr(smoke.runpy, "run_path", lambda _: {"_PROBE": FIXTURE_PROBE})
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps({"token": "private", "files": [{}, {}]})
            )
        assert kwargs["env"]["E2E_LIBRARY_DOWNLOAD_SURFACE"] == "work"
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"stats": {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0}}
            ),
        )

    monkeypatch.setattr(smoke.subprocess, "run", run)
    assert smoke.main() == 0
    assert calls[0]["input"] == FIXTURE_PROBE.encode()
    output = capsys.readouterr().out
    assert "private" not in output
    assert json.loads(output)["surface"] == "work"


def test_invalid_surface_never_executes_probe(monkeypatch, capsys):
    monkeypatch.setenv("S37_LIVE_LIBRARY_DOWNLOAD_BROWSER", "1")
    monkeypatch.setenv("S37_LIBRARY_DOWNLOAD_SURFACE", "external")
    assert smoke.main() == 2
    assert json.loads(capsys.readouterr().out)["stage"] == "invalid_surface"


def test_explicit_owner_option_selects_only_the_reviewed_actor(monkeypatch, capsys):
    monkeypatch.setenv("S37_LIVE_LIBRARY_DOWNLOAD_BROWSER", "1")
    monkeypatch.setattr(smoke.runpy, "run_path", lambda _: {"_BROWSER_PROBE": FIXTURE_PROBE})
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps({"token": "PRIVATE", "files": [{}, {}]})
            )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "stats": {"expected": 2, "unexpected": 0, "skipped": 0, "flaky": 0},
                }
            ),
        )

    monkeypatch.setattr(smoke.subprocess, "run", run)
    assert smoke.main(["--acceptance-owner", "s38"]) == 0
    assert calls[0]["input"] == b"owner_email='s38-video-acceptance@example.com'"
    assert "PRIVATE" not in capsys.readouterr().out
