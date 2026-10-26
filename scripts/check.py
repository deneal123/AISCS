"""Run the same fail-fast checks from PowerShell, Make and CI."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def commands(role: str, *, skip_build: bool = False, skip_mcp: bool = False) -> list[list[str]]:
    py = sys.executable
    cli = {"text": "textctl", "presentation": "presentationctl", "publications": "pubctl"}[role]
    steps = [[py, "scripts/check_repository.py"], [cli, "validate"]]
    if role == "text":
        steps.append([py, "scripts/audit_chapter1.py"])
    steps += [
        [py, "-m", "ruff", "check", "service", "tests", "scripts"],
        [py, "-m", "pytest", "-q"],
    ]
    if not skip_build:
        documents = {
            "text": ["TEXT-001"],
            "presentation": ["PRES-001", "PRES-002"],
            "publications": ["PUB-TEMPLATE-001"],
        }[role]
        steps += [[cli, "build", document, "--profile", "draft"] for document in documents]
    if not skip_mcp:
        steps.append([py, "scripts/mcp-smoke.py"])
    return steps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-mcp", action="store_true")
    args = parser.parse_args()
    config = json.loads((ROOT / "sidecar.json").read_text(encoding="utf-8"))
    role = config["name"].removeprefix("aspa-").removesuffix("-sidecar")
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["version"] == metadata["project"]["version"]
    for argv in commands(role, skip_build=args.skip_build, skip_mcp=args.skip_mcp):
        print("Running: " + " ".join(argv), flush=True)
        result = subprocess.run(argv, cwd=ROOT, check=False)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
