"""Record the boundary of the S741 author repository's flyvis provenance."""

# ruff: noqa: E501 -- exact release-boundary statements and locators remain readable.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-25"
REPO = "https://github.com/nalin-dhiman/Connectome-Constrained-Neural-Networks/tree/336e0d12a6edd92a7340cfffb71985a3879055ce"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit = json.loads((DATA / "drosophila-connectome-audit.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    entry = next(x for x in audit["entries"] if x["source_id"] == "S741")
    row = next(x for x in matrix["rows"] if "S741" in x["source_ids"])
    version = entry["extraction"]["connectome_version"]
    if version["state"] != "not_reported":
        raise ValueError("S741 release state changed")
    version.update(
        reason="The article describes a fixed flyvis-derived graph. The author repository excludes raw flyvis datasets and requires externally supplied FLYVIS_REPO_ROOT and FLYVIS_BASELINE_CHECKPOINT; it therefore does not pin the source-connectome or scaffold release used for the reported run.",
        checked_at=DATE,
        locators=[
            {"url": "https://arxiv.org/html/2604.04033v1", "locator": "Methods 4.1; Section 12"},
            {"url": REPO + "/data/README.md", "locator": "Data README: flyvis datasets and checkpoints excluded"},
            {"url": REPO + "/README.md", "locator": "Setup: FLYVIS_REPO_ROOT and FLYVIS_BASELINE_CHECKPOINT supplied externally"},
        ],
    )
    entry["author_repo_review"] = {
        "commit": "336e0d12a6edd92a7340cfffb71985a3879055ce",
        "checked_at": DATE,
        "conclusion": "matching compiled scaffold counts do not establish the release used for this result",
        "locators": version["locators"][1:],
    }
    row["limitations"] += " Author repository excludes source flyvis datasets and needs an external baseline checkpoint; its scaffold counts do not pin the reported connectome release."
    row["locators"].extend(
        [
            {"source_id": "S741", "url": REPO + "/data/README.md", "locator": "excluded flyvis data"},
            {"source_id": "S741", "url": REPO + "/README.md", "locator": "external dataset and checkpoint setup"},
        ]
    )
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s741-flyvis-lineage-review")
        atomic_write_json(DATA / "drosophila-connectome-audit.json", audit)
        atomic_write_json(DATA / "evidence-matrix.json", matrix)
        print(f"Applied S741 lineage review; snapshot: {snapshot}")
    else:
        print("Dry run: S741 author repository does not pin the source release")


if __name__ == "__main__":
    main()
