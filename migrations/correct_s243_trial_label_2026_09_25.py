"""Correct a trial-registration identifier mislabeled as a patent ID."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    row = next(item for item in matrix["rows"] if item["source_ids"] == ["S243"])
    old = "patent_id=NCT04662905"
    if not row["verified_evidence"].startswith(old):
        raise ValueError("Unexpected S243 evidence state")
    row["verified_evidence"] = row["verified_evidence"].replace(
        old, "trial_registration=NCT04662905", 1
    )
    snapshot = snapshot_repository(DATA, label="pre-s243-trial-label-correction")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    print(f"Corrected S243 trial label; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
