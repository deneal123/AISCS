"""Fail-fast repository, scientific-registry and protocol checks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-mcp", action="store_true", help="Skip additional HTTP/stdio smoke")
    args = parser.parse_args()
    py = sys.executable
    steps = [
        [py, "scripts/check_repository.py"],
        [py, "-m", "service.cli", "validate"],
        [py, "-m", "service.cli", "novelty-check"],
        [py, "-m", "ruff", "check", "service", "tests", "migrations", "scripts"],
        [py, "-m", "pytest", "-q"],
        [py, "scripts/check_release.py"],
    ]
    if not args.skip_mcp:
        steps.append([py, "scripts/smoke.py"])
    for argv in steps:
        print("Running: " + " ".join(argv), flush=True)
        if argv[-1] == "novelty-check":
            result = subprocess.run(
                argv, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False
            )
            if result.returncode:
                print(result.stdout + result.stderr)
            else:
                payload = json.loads(result.stdout)
                print(json.dumps({"ok": payload["ok"], "variant_count": payload["variant_count"]}))
        else:
            result = subprocess.run(argv, cwd=ROOT, check=False)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
