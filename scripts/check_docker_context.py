"""Verify actual BuildKit context contents without exposing local secrets."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    work = ROOT / ".work"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="docker-context-", dir=work) as temporary:
        target = Path(temporary).resolve()
        if not target.is_relative_to(work.resolve()):
            raise ValueError("Context export is outside the scratch directory")
        result = subprocess.run(
            ["docker", "build", "-f", "-", "--output", f"type=local,dest={target}", "."],
            input="FROM scratch\nCOPY . /context\n",
            text=True,
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise SystemExit(result.stderr)
        context = target / "context"
        actual = sorted(
            p.relative_to(context).as_posix() for p in context.rglob("*") if p.is_file()
        )
        forbidden = {".git", ".work", ".knowledge", ".venv", "__pycache__", "tests", "build"}
        if any(set(Path(name).parts) & forbidden for name in actual):
            raise ValueError("Disposable or private files reached the Docker context")
        if any(Path(name).name.startswith(".env") for name in actual):
            raise ValueError("An environment file reached the Docker context")
        required = {
            "pyproject.toml",
            "uv.lock",
            "README.md",
            "docker/entrypoint.sh",
            "service/app.py",
            "data/records.json",
        }
        if not required.issubset(actual):
            raise ValueError("Runtime inputs missing from Docker context")
        print(
            json.dumps({"ok": True, "context_files": len(actual), "private_state_included": False})
        )


if __name__ == "__main__":
    main()
