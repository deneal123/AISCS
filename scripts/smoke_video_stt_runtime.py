"""Explicit dev fixture probe. Input stays private; only aggregate results print."""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path

from smoke_workspace_restart import idle

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if os.getenv("S38_STT_RUNTIME_LIVE") != "1":
        raise ValueError("opt_in_required")
    idle()
    credentials = json.loads((ROOT / ".env.s38").read_text(encoding="utf-8"))
    audio = (ROOT / "frontend/test-results/s38-stt-runtime/controlled.wav").read_bytes()
    source = (ROOT / "backend/tests/live_video_stt_probe.py").read_text(
        encoding="utf-8"
    )
    wire = {
        "opt_in": True,
        "token": credentials["token"],
        "audio": base64.b64encode(audio).decode(),
    }
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", source],
        input=json.dumps(wire),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    report = json.loads(result.stdout) if result.returncode == 0 else None
    if not isinstance(report, dict):
        raise ValueError("probe_failed")
    print(json.dumps(report))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({"status": "failed", "stage": "runner_boundary"}))
