"""Snapshot local SIM-evaluation receipt metadata; does not redistribute input files."""

import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
assessment = ROOT / "simulations/data/assessment.json"
registry = ROOT / "simulations/data/registry.json"
report = ROOT / "simulations/REPORT.md"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


checks = json.loads(assessment.read_text(encoding="utf-8"))["candidates"]
repos = json.loads(registry.read_text(encoding="utf-8"))["candidates"]
assert len(checks) == len(repos) == 32
assert {item["id"] for item in checks} == {item["id"] for item in repos}
states = Counter((row["id"], row["status"]) for item in checks for row in item["checks"])
paths = sorted(
    {
        value
        for item in checks
        for row in item["checks"]
        for value in row.get("evidence", [])
        if value.startswith("research/.work/")
    }
)
receipts = []
for relative in paths:
    path = ROOT / relative
    if not path.is_file():
        receipts.append({"path": relative, "available": False})
    else:
        receipts.append(
            {
                "path": relative,
                "available": True,
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
        )
output = {
    "created_on": date.today().isoformat(),
    "scope": "Local file identity, not a reproduction of experiments or public access",
    "source_files": {
        str(p.relative_to(ROOT)).replace("\\", "/"): digest(p)
        for p in (assessment, registry, report)
    },
    "candidate_count": len(checks),
    "passed_by_check": {
        key: count for (key, status), count in states.items() if status == "passed"
    },
    "blocked_by_check": {
        key: count for (key, status), count in states.items() if status == "blocked"
    },
    "unique_receipt_count": len(receipts),
    "missing_receipt_count": sum(not item["available"] for item in receipts),
    "receipts": receipts,
}
target = HERE / "simulator-receipts-manifest.json"
target.write_text(
    json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
)
print(json.dumps(
    {key: value for key, value in output.items() if key != "receipts"}, ensure_ascii=False
))
