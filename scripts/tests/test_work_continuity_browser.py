"""Native continuity runner cannot leak transport errors or invoke a model suite."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "work_continuity_smoke",
    Path(__file__).parents[1] / "smoke_work_continuity_browser.py",
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_requires_explicit_live_opt_in(monkeypatch, capsys):
    monkeypatch.delenv("S37_LIVE_WORK_CONTINUITY", raising=False)
    monkeypatch.setattr(
        smoke.subprocess, "run", lambda *args, **kwargs: pytest.fail("dispatched")
    )
    assert smoke.main() == 2
    assert "opt_in_required" in capsys.readouterr().out


def test_unknown_matrix_cannot_dispatch_an_unreviewed_suite(monkeypatch, capsys):
    monkeypatch.setenv("S37_LIVE_WORK_CONTINUITY", "1")
    monkeypatch.setattr(
        smoke.subprocess, "run", lambda *args, **kwargs: pytest.fail("dispatched")
    )
    assert smoke.main("document-provider") == 2
    assert "invalid_matrix" in capsys.readouterr().out


@pytest.mark.parametrize("value", [True, -1, "3", None])
def test_invalid_counts_cannot_claim_browser_success(value):
    with pytest.raises(ValueError, match="invalid_report"):
        smoke._counts(
            {
                "stats": {
                    "expected": value,
                    "unexpected": 0,
                    "skipped": 0,
                    "flaky": 0,
                }
            }
        )


def test_private_failure_body_never_reaches_output(monkeypatch, capsys):
    monkeypatch.setenv("S37_LIVE_WORK_CONTINUITY", "1")
    monkeypatch.setattr(
        smoke.runpy,
        "run_path",
        lambda path: (_ for _ in ()).throw(ValueError("PRIVATE_AUTH_BODY_MARKER")),
    )
    assert smoke.main() == 1
    output = capsys.readouterr().out
    assert "browser_probe_unavailable" in output
    assert "PRIVATE_AUTH_BODY_MARKER" not in output


def test_matrix_excludes_paid_document_or_agent_paths():
    assert len(smoke.CASES) == 3
    assert not any(
        word in "|".join(smoke.CASES) for word in ("document", "PDF", "agent")
    )


def test_failure_diagnostics_project_only_closed_stage_and_reason():
    report = {
        "suites": [
            {
                "specs": [
                    {
                        "title": smoke.CASES[1] + " PRIVATE_CASE_MARKER",
                        "tests": [
                            {
                                "results": [
                                    {
                                        "status": "failed",
                                        "error": {
                                            "message": "Timeout .chakra-toast__inner PRIVATE_AUTH_BODY_MARKER",
                                        },
                                    }
                                ]
                            }
                        ],
                    }
                ]
            }
        ]
    }
    assert smoke._failure_codes(report) == [
        {"stage": "intake", "reason": "toast_observation"}
    ]


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("matrix", ["core", "attachment-history"])
def test_exact_browser_counts_and_private_environment(
    monkeypatch, capsys, failed, matrix
):
    import json
    from types import SimpleNamespace

    monkeypatch.setenv("S37_LIVE_WORK_CONTINUITY", "1")
    calls = []

    def fixture(path):
        if str(path).endswith("smoke_library_download_browser.py"):
            return {
                "_owned_probe": lambda source, owner: source if owner == "s38" else None
            }
        return {"_PROBE": "read-only-fixture"}

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "docker":
            return SimpleNamespace(
                returncode=0, stdout=json.dumps({"token": "PRIVATE_TOKEN"})
            )
        assert kwargs["env"]["E2E_AUTH_TOKEN"] == "PRIVATE_TOKEN"
        assert kwargs["env"]["E2E_BASE_URL"] == "http://localhost:3001"
        assert kwargs["env"]["E2E_LIVE_WORK_HUB"] == "1"
        project = "chromium" if "--project=chromium" in command else "mobile-chrome"
        assert (
            f"--output=test-results/s37-work-continuity/{matrix}/{project}" in command
        )
        index = 0 if project == "chromium" else 1
        count = len(smoke.MATRICES[matrix][index])
        stats = {"expected": count, "unexpected": int(failed), "skipped": 0, "flaky": 0}
        return SimpleNamespace(
            returncode=int(failed),
            stdout=json.dumps({"stats": stats, "errors": ["PRIVATE_RESPONSE_BODY"]}),
        )

    monkeypatch.setattr(smoke.runpy, "run_path", fixture)
    monkeypatch.setattr(smoke.subprocess, "run", run)
    assert smoke.main(matrix) == int(failed)
    assert len(calls) == (2 if failed else 3)
    output = capsys.readouterr().out
    assert "PRIVATE_TOKEN" not in output and "PRIVATE_RESPONSE_BODY" not in output
    assert ("passed" if not failed else "failed") in output
