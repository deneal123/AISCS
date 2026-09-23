"""Audit S23 production additions against a local dirty-tree snapshot.

The agents submodule already contains useful uncommitted S22/S23 work.  A plain
``git diff --numstat`` cannot distinguish that inherited slice from later work and
the superproject sees only a gitlink.  This script snapshots the current submodule
tree locally, registers only reviewed S23 paths, and reports later additions.

Only Python below ``service/`` is production scope.  Tests, docs, scripts and config
are reported separately.  Lines deleted from one production file and inserted
unchanged into another are classified as relocation and do not satisfy the target.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOT = ROOT / ".s23-local"
MANIFEST = LOCAL_ROOT / "baseline.json"
SNAPSHOT_ROOT = LOCAL_ROOT / "tree"
TARGET = 5_000

# Reviewed S23 production paths present before this completion phase.  S22-only
# ``auto_mode`` and ``workspace_client`` hunks are intentionally absent.
REGISTERED_TRACKED = (
    "service/domain/client/calls/chat.py",
    "service/domain/client/calls/streaming.py",
    "service/domain/client/health.py",
    "service/domain/client/providers/function_dialect.py",
    "service/domain/client/providers/gigachat.py",
    "service/domain/client/providers/spec.py",
    "service/domain/runners/chat_run.py",
    "service/domain/runners/tool_loop.py",
    "service/domain/tools/workspace_tools.py",
)
REGISTERED_UNTRACKED = (
    "service/domain/client/providers/gigachat_schema.py",
    "service/presentation/cli/__init__.py",
    "service/presentation/cli/gigachat_tools_smoke.py",
)


@dataclass(frozen=True, slots=True)
class Delta:
    additions: list[str]
    deletions: list[str]


def _run(*args: str) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tracked_additions(path: str) -> int:
    output = _run("git", "diff", "--numstat", "--", path).strip()
    total = 0
    for row in output.splitlines():
        added, *_ = row.split("\t")
        if added.isdigit():
            total += int(added)
    return total


def _registered_slice() -> tuple[int, list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    total = 0
    for path in REGISTERED_TRACKED:
        patch = _run("git", "diff", "--no-ext-diff", "--", path).encode()
        additions = _tracked_additions(path)
        total += additions
        rows.append(
            {
                "path": path,
                "kind": "tracked_hunks",
                "sha256": _sha256(patch),
                "additions": additions,
            }
        )
    for path in REGISTERED_UNTRACKED:
        source = ROOT / path
        data = source.read_bytes()
        additions = len(source.read_text(encoding="utf-8").splitlines())
        total += additions
        rows.append(
            {
                "path": path,
                "kind": "untracked_file",
                "sha256": _sha256(data),
                "additions": additions,
            }
        )
    return total, rows


def _python_files(root: Path, prefix: str) -> dict[str, list[str]]:
    base = root / prefix
    if not base.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
        for path in sorted(base.rglob("*.py"))
        if path.is_file()
    }


def _write_snapshot() -> None:
    if SNAPSHOT_ROOT.exists():
        shutil.rmtree(SNAPSHOT_ROOT)
    for prefix in ("service", "tests"):
        for relative, lines in _python_files(ROOT, prefix).items():
            target = SNAPSHOT_ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create() -> None:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    registered, rows = _registered_slice()
    _write_snapshot()
    manifest = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "registered_current_s23": registered,
        "registered_sources": rows,
        "scope": "agents/service/**/*.py",
        "target": TARGET,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"baseline={MANIFEST}")
    print(f"registered_current_s23={registered}")


def _delta(before: list[str], after: list[str]) -> Delta:
    additions: list[str] = []
    deletions: list[str] = []
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"delete", "replace"}:
            deletions.extend(before[i1:i2])
        if tag in {"insert", "replace"}:
            additions.extend(after[j1:j2])
    return Delta(additions, deletions)


def _scope_delta(prefix: str) -> Delta:
    before = _python_files(SNAPSHOT_ROOT, prefix)
    after = _python_files(ROOT, prefix)
    additions: list[str] = []
    deletions: list[str] = []
    for path in sorted(set(before) | set(after)):
        change = _delta(before.get(path, []), after.get(path, []))
        additions.extend(change.additions)
        deletions.extend(change.deletions)
    return Delta(additions, deletions)


def _relocated(additions: list[str], deletions: list[str]) -> int:
    # Exact non-empty lines removed elsewhere are refactor volume, not new product code.
    added = Counter(line for line in additions if line.strip())
    deleted = Counter(line for line in deletions if line.strip())
    return sum(min(count, deleted.get(line, 0)) for line, count in added.items())


def report() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    production = _scope_delta("service")
    tests = _scope_delta("tests")
    relocated = _relocated(production.additions, production.deletions)
    post_baseline = len(production.additions) - relocated
    registered = int(manifest["registered_current_s23"])
    total = registered + post_baseline
    rows = {
        "registered_current_s23": registered,
        "post_baseline_production_additions": post_baseline,
        "production_deletions": len(production.deletions),
        "relocated_lines_excluded": relocated,
        "test_additions": len(tests.additions),
        "test_deletions": len(tests.deletions),
        "total_production_additions": total,
        "target": int(manifest.get("target", TARGET)),
    }
    for key, value in rows.items():
        print(f"{key}\t{value}")
    return 0 if total >= rows["target"] else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "report"))
    args = parser.parse_args()
    if args.action == "create":
        create()
        return 0
    if not MANIFEST.exists():
        parser.error("baseline missing; run create before changing production files")
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
