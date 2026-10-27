"""Opt-in native Work continuity, confined to the existing S38 dev actor.

No model calls or balance mutation. Existing browser finally blocks remove
their synthetic threads, workspace containers and owned Library fixtures.
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    "new edits during an acknowledged server write",
    "passive view, direct intake, edit and responsive layout",
    "lease collision and revision conflict",
)
EXTRA_CASES = (
    "chat attachment persists in Library without passive sandbox activation",
    "history diff and confirmed revert restore the imported revision",
)
MATRICES = {
    "core": (CASES, CASES[:2]),
    "attachment-history": (EXTRA_CASES, EXTRA_CASES),
}


def _counts(report: dict) -> dict[str, int]:
    counts = {
        key: report["stats"][key]
        for key in ("expected", "unexpected", "skipped", "flaky")
    }
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise ValueError("invalid_report")
    return counts


def _failure_codes(report: dict) -> list[dict[str, str]]:
    """Diagnose only the closed synthetic matrix, never print runner errors."""
    failures = []
    stages = ("save_race", "intake", "conflict", "attachment", "history")
    pending = list(report.get("suites", []))
    while pending:
        suite = pending.pop()
        pending.extend(suite.get("suites", []))
        for spec in suite.get("specs", []):
            stage = next(
                (
                    stages[index]
                    for index, case in enumerate(CASES + EXTRA_CASES)
                    if case in spec.get("title", "")
                ),
                "unknown",
            )
            for test in spec.get("tests", []):
                for result in test.get("results", []):
                    if result.get("status") not in {
                        "failed",
                        "timedOut",
                        "interrupted",
                    }:
                        continue
                    message = result.get("error", {}).get("message", "")
                    reason = (
                        "toast_observation"
                        if ".chakra-toast__inner" in message
                        else "geometry"
                        if "toBeLessThanOrEqual" in message
                        else "content"
                        if "toHaveValue" in message
                        else "timeout"
                        if "Timeout" in message
                        else "unknown"
                    )
                    failures.append({"stage": stage, "reason": reason})
    return failures


def main(matrix: str = "core") -> int:
    if os.getenv("S37_LIVE_WORK_CONTINUITY") != "1":
        print(json.dumps({"status": "blocked", "stage": "opt_in_required"}))
        return 2
    if matrix not in MATRICES:
        print(json.dumps({"status": "blocked", "stage": "invalid_matrix"}))
        return 2
    try:
        library = runpy.run_path(
            str(ROOT / "scripts/smoke_library_download_browser.py")
        )
        fixture_source = runpy.run_path(
            str(ROOT / "backend/tests/test_document_library_download_live.py")
        )["_PROBE"]
        source = library["_owned_probe"](fixture_source, "s38")
        prepared = subprocess.run(
            ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
            input=source.encode("utf-8"),
            capture_output=True,
            timeout=30,
            check=False,
        )
        fixture = json.loads(prepared.stdout)
        if prepared.returncode or not isinstance(fixture.get("token"), str):
            print(json.dumps({"status": "blocked", "stage": "dev_actor_unavailable"}))
            return 2
        environment = os.environ.copy()
        environment.update(
            E2E_BASE_URL="http://localhost:3001",
            E2E_LIVE_WORK_HUB="1",
            E2E_AUTH_TOKEN=fixture["token"],
        )
        outcomes = []
        # The two-context case is intentionally desktop-only; do not count a
        # mobile skip as successful qualification of that capability.
        for project, cases in zip(
            ("chromium", "mobile-chrome"), MATRICES[matrix], strict=True
        ):
            result = subprocess.run(
                [
                    "npx.cmd" if os.name == "nt" else "npx",
                    "playwright",
                    "test",
                    "tests/e2e/work-hub.live.spec.js",
                    "--config=tests/e2e/playwright.config.js",
                    f"--project={project}",
                    "--grep",
                    "|".join(cases),
                    "--workers=1",
                    "--reporter=json",
                    f"--output=test-results/s37-work-continuity/{matrix}/{project}",
                ],
                cwd=ROOT / "frontend",
                env=environment,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
            report = json.loads(result.stdout)
            counts = _counts(report)
            passed = not result.returncode and counts == {
                "expected": len(cases),
                "unexpected": 0,
                "skipped": 0,
                "flaky": 0,
            }
            outcomes.append(
                {
                    "project": project,
                    "passed": passed,
                    "counts": counts,
                    "failures": _failure_codes(report) if not passed else [],
                }
            )
            if not passed:
                break
        passed = len(outcomes) == 2 and all(item["passed"] for item in outcomes)
        # Raw Playwright failures can include request headers/URLs and DOM text.
        # Never print its JSON, subprocess stderr or exception representation.
        print(
            json.dumps(
                {
                    "status": "passed" if passed else "failed",
                    "matrix": matrix,
                    "cases": outcomes,
                }
            )
        )
        return 0 if passed else 1
    except (
        OSError,
        ImportError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
    ):
        print(json.dumps({"status": "failed", "stage": "browser_probe_unavailable"}))
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", choices=tuple(MATRICES), default="core")
    raise SystemExit(main(parser.parse_args().matrix))
