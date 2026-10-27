#!/usr/bin/env python3
"""Offline parity gate for the versioned Chat/Agents/Work wire contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COPIES = {
    "agents": ROOT / "agents" / "service" / "protocol_manifest.json",
    "backend": (
        ROOT
        / "backend"
        / "service"
        / "infrastructure"
        / "agents_client"
        / "contracts"
        / "protocol_manifest.json"
    ),
    "frontend": (
        ROOT
        / "frontend"
        / "src"
        / "features"
        / "chat"
        / "model"
        / "protocolManifest.json"
    ),
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest_root")
    return value


def main() -> int:
    missing = [name for name, path in COPIES.items() if not path.is_file()]
    if missing:
        print(
            f"protocol manifest missing: {', '.join(sorted(missing))}", file=sys.stderr
        )
        return 1
    loaded = {name: _load(path) for name, path in COPIES.items()}
    canonical = loaded["agents"]
    mismatched = [name for name, value in loaded.items() if value != canonical]
    if mismatched:
        print(
            f"protocol manifest mismatch: {', '.join(sorted(mismatched))}",
            file=sys.stderr,
        )
        return 1
    for contract in (
        "ide_command.py",
        "harness_protocol.py",
        "harness_refinement.py",
        "block_patch.py",
        "document_review.py",
    ):
        if (ROOT / "agents/service/shared" / contract).read_bytes() != (
            ROOT / "backend/service/shared" / contract
        ).read_bytes():
            print(f"portable contract mismatch: {contract}", file=sys.stderr)
            return 1
    print(
        "protocol manifest aligned: "
        f"{canonical.get('version')} across {', '.join(sorted(COPIES))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
