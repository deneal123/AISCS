"""Check consistency of the article inventory with the recorded SIM snapshot.

This does not reproduce the original experiments or validate biology.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
parser = argparse.ArgumentParser()
parser.add_argument(
    "--verify-receipts",
    action="store_true",
    help="Read and hash every local receipt recorded in the manifest",
)
args = parser.parse_args()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


inventory = read(HERE / "simulator-inventory.json")["candidates"]
manifest = read(HERE / "simulator-receipts-manifest.json")
assessment = read(ROOT / "simulations/data/assessment.json")["candidates"]
registry = read(ROOT / "simulations/data/registry.json")["candidates"]
figure = read(HERE / "figures/tool-check-counts.provenance.json")


def by_id(rows):
    result = {row["id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate candidate ID")
    return result


inventory_by_id, assessment_by_id, registry_by_id = map(by_id, (inventory, assessment, registry))
if not (len(inventory) == 32 and inventory_by_id.keys() == assessment_by_id.keys()
        == registry_by_id.keys()):
    raise ValueError("Candidate sets differ")

counts = Counter()
for candidate_id, item in inventory_by_id.items():
    assessed = assessment_by_id[candidate_id]
    registered = registry_by_id[candidate_id]
    if (item["commit"] != assessed["commit"] or item["commit"] != registered["commit"]
            or item["repository"] != registered["repository"]):
        raise ValueError(f"Repository identity differs: {candidate_id}")
    checks = {check["id"]: check for check in assessed["checks"]}
    if len(checks) != len(assessed["checks"]) or set(checks) != set(item["checks"]):
        raise ValueError(f"Check set differs: {candidate_id}")
    for check_id, check in checks.items():
        if item["checks"][check_id] != check["status"]:
            raise ValueError(f"Status differs: {candidate_id}/{check_id}")
        if item["evidence"].get(check_id, []) != check.get("evidence", []):
            raise ValueError(f"Evidence references differ: {candidate_id}/{check_id}")
        counts[(check_id, check["status"])] += 1

for relative, recorded_hash in manifest["source_files"].items():
    if sha256(ROOT / relative) != recorded_hash:
        raise ValueError(f"Source changed since receipt snapshot: {relative}")
for key, expected in figure["counts"].items():
    if counts[(key, "passed")] != expected or manifest["passed_by_check"][key] != expected:
        raise ValueError(f"Figure count differs: {key}")
if figure["candidate_count"] != len(inventory):
    raise ValueError("Figure denominator differs")
if figure["input_sha256"] != sha256(HERE / "simulator-receipts-manifest.json"):
    raise ValueError("Figure input manifest differs")

verified_receipts = None
if args.verify_receipts:
    receipt_paths = set()
    for receipt in manifest["receipts"]:
        relative = receipt["path"]
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT.resolve()) or relative in receipt_paths:
            raise ValueError(f"Invalid or duplicate receipt path: {relative}")
        receipt_paths.add(relative)
        if not receipt.get("available") or not path.is_file():
            raise ValueError(f"Receipt unavailable: {relative}")
        if path.stat().st_size != receipt["bytes"] or sha256(path) != receipt["sha256"]:
            raise ValueError(f"Receipt content changed: {relative}")
    if len(receipt_paths) != manifest["unique_receipt_count"]:
        raise ValueError("Receipt count differs")
    verified_receipts = len(receipt_paths)

print(json.dumps({
    "candidate_count": len(inventory),
    "checked_statuses": sum(counts.values()),
    "figure_counts": figure["counts"],
    "verified_receipts": verified_receipts,
    "scope": "snapshot consistency only; not independent receipt or biological verification",
}, ensure_ascii=False))
