"""Create and inspect a local, non-versioned S19 change baseline.

The superproject already contains unrelated staged and unstaged S11-S18 work.
This utility snapshots hunk digests before further S19 work so the delivery
report can distinguish the inherited dirty tree from subsequent additions.
It uses only the standard library and writes below ``.s19-local/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".s19-local" / "baseline.json"
LAYERS = ("workspace/service", "backend/service", "agents/service", "frontend/src")


def _git_diff(path: str) -> str:
    result = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--", path],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def _numstat(path: str) -> tuple[int, int]:
    result = subprocess.run(
        ["git", "diff", "--numstat", "--", path],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    additions = deletions = 0
    for line in result.stdout.splitlines():
        added, removed, *_ = line.split("\t", 2)
        if added.isdigit():
            additions += int(added)
        if removed.isdigit():
            deletions += int(removed)
    return additions, deletions


def _hunks(diff: str) -> list[dict[str, str]]:
    current_file = ""
    current: list[str] = []
    out: list[dict[str, str]] = []
    for line in diff.splitlines(keepends=True):
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
        if line.startswith("@@ "):
            if current:
                text = "".join(current)
                out.append(
                    {"path": current_file, "sha256": hashlib.sha256(text.encode()).hexdigest()}
                )
            current = [line]
        elif current:
            current.append(line)
    if current:
        text = "".join(current)
        out.append({"path": current_file, "sha256": hashlib.sha256(text.encode()).hexdigest()})
    return out


def create(output: Path) -> None:
    layers = {
        layer: {"hunks": _hunks(_git_diff(layer)), "numstat": list(_numstat(layer))}
        for layer in LAYERS
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "version": 1,
                "created_at": datetime.now(UTC).isoformat(),
                "layers": layers,
                "registered_current_s19": {layer: 0 for layer in LAYERS},
                "note": "Inherited hunks; S19 additions are reported separately.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def verify(output: Path) -> int:
    saved = json.loads(output.read_text(encoding="utf-8"))
    expected = saved.get("layers") if isinstance(saved, dict) else {}
    mismatches = []
    for layer in LAYERS:
        current = _hunks(_git_diff(layer))
        baseline = expected.get(layer, {})
        expected_hunks = baseline if isinstance(baseline, list) else baseline.get("hunks", [])
        if current != expected_hunks:
            mismatches.append(layer)
    if mismatches:
        print("baseline drift: " + ", ".join(mismatches))
        return 1
    print("S19 baseline matches")
    return 0


def register(output: Path, layer: str, lines: int) -> None:
    if layer not in LAYERS or lines < 0:
        raise ValueError("invalid layer or line count")
    saved = json.loads(output.read_text(encoding="utf-8"))
    registered = saved.setdefault("registered_current_s19", {name: 0 for name in LAYERS})
    registered[layer] = int(registered.get(layer, 0)) + lines
    output.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def report(output: Path) -> int:
    saved = json.loads(output.read_text(encoding="utf-8"))
    registered = saved.get("registered_current_s19", {})
    rows: list[tuple[str, int, int, int]] = []
    for layer in LAYERS:
        raw_layer = saved.get("layers", {}).get(layer, {})
        if isinstance(raw_layer, list):
            print("baseline lacks numstat; recreate only before counting new work")
            return 3
        baseline = raw_layer.get("numstat", [0, 0])
        current_additions, current_deletions = _numstat(layer)
        after_baseline = max(0, current_additions - int(baseline[0]))
        counted = after_baseline + int(registered.get(layer, 0))
        rows.append((layer, counted, current_deletions, int(registered.get(layer, 0))))
    print("layer\tproduction_additions\tcurrent_deletions\tregistered_current_slice")
    for row in rows:
        print("\t".join(map(str, row)))
    total = sum(row[1] for row in rows)
    print(f"total_production_additions\t{total}")
    return 0 if total >= 5_000 else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "verify", "register", "report"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--layer", choices=LAYERS)
    parser.add_argument("--lines", type=int)
    args = parser.parse_args()
    if args.action == "create":
        create(args.output)
        print(args.output)
        return 0
    if args.action == "register":
        if args.layer is None or args.lines is None:
            parser.error("register requires --layer and --lines")
        register(args.output, args.layer, args.lines)
        return 0
    if args.action == "report":
        return report(args.output)
    return verify(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
