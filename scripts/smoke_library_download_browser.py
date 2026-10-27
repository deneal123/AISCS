"""Opt-in read-only downloads from retained Chat cards or account Work Library."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ACCEPTANCE_OWNERS = {
    "s37": "s37-e2e-391e5206659a3654@example.com",
    "s38": "s38-video-acceptance@example.com",
}


def _owned_probe(source: str, acceptance_owner: str) -> str:
    """Only named isolated acceptance actors; never arbitrary user impersonation."""
    original = _ACCEPTANCE_OWNERS["s37"]
    if acceptance_owner not in _ACCEPTANCE_OWNERS or source.count(original) != 1:
        raise ValueError("invalid_acceptance_fixture")
    return source.replace(original, _ACCEPTANCE_OWNERS[acceptance_owner], 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--acceptance-owner", choices=tuple(_ACCEPTANCE_OWNERS), default="s37"
    )
    args = parser.parse_args(argv or [])
    if os.getenv("S37_LIVE_LIBRARY_DOWNLOAD_BROWSER") != "1":
        print(json.dumps({"status": "blocked", "stage": "opt_in_required"}))
        return 2
    try:
        surface = os.getenv("S37_LIBRARY_DOWNLOAD_SURFACE", "chat")
        if surface not in {"chat", "work"}:
            print(json.dumps({"status": "blocked", "stage": "invalid_surface"}))
            return 2
        # The owning backend environment supplies SQL/HTTP test dependencies.
        probe = runpy.run_path(
            str(ROOT / "backend/tests/test_document_library_download_live.py")
        )["_BROWSER_PROBE" if surface == "chat" else "_PROBE"]
        probe = _owned_probe(probe, args.acceptance_owner)
        prepared = subprocess.run(
            ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
            input=probe.encode(),
            capture_output=True,
            timeout=30,
            check=False,
        )
        fixture = json.loads(prepared.stdout)
        if prepared.returncode or len(fixture.get("files", [])) != 2:
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "stage": "retained_card_fixture_unavailable"
                        if surface == "chat"
                        else "owned_library_fixture_unavailable",
                    }
                )
            )
            return 2
        environment = os.environ.copy()
        environment.update(
            E2E_BASE_URL="http://localhost:3001",
            E2E_LIVE_LIBRARY_DOWNLOAD="1",
            E2E_LIBRARY_DOWNLOAD_SURFACE=surface,
            E2E_AUTH_TOKEN=fixture["token"],
            E2E_LIBRARY_DOWNLOAD_FIXTURE=json.dumps(fixture["files"]),
        )
        result = subprocess.run(
            [
                "npx.cmd" if os.name == "nt" else "npx",
                "playwright",
                "test",
                "tests/e2e/library-download.live.spec.js",
                "--config=tests/e2e/playwright.config.js",
                "--project=chromium",
                "--project=mobile-chrome",
                "--workers=1",
                "--reporter=json",
                "--output=test-results/s37-library-download",
            ],
            cwd=ROOT / "frontend",
            env=environment,
            capture_output=True,
            encoding="utf-8",
            timeout=240,
            check=False,
        )
        report = json.loads(result.stdout)
        stats = report["stats"]
        # Never print Playwright failure messages, request URLs, cookie headers
        # or its raw JSON report. Counts alone cannot imply semantic acceptance.
        counts = {
            key: stats[key] for key in ("expected", "unexpected", "skipped", "flaky")
        }
        if any(type(value) is not int or value < 0 for value in counts.values()):
            raise ValueError("invalid_report")
        passed = not result.returncode and counts == {
            "expected": 2,
            "unexpected": 0,
            "skipped": 0,
            "flaky": 0,
        }
        print(
            json.dumps(
                {
                    "status": "passed" if passed else "failed",
                    "surface": surface,
                    "counts": counts,
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
    raise SystemExit(main(sys.argv[1:]))
