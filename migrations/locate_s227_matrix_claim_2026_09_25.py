"""Pin MuSACo's source-selection claim to its author preprint."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    rows = [
        row for row in matrix["rows"]
        if row["source_ids"] == ["S227"]
        and row["locators"][0]["locator"] == "validated evidence row"
    ]
    if len(rows) != 1:
        raise ValueError("Expected one generic S227 row")
    rows[0]["locators"] = [{
        "source_id": "S227",
        "url": "https://arxiv.org/html/2508.12522v2",
        "locator": (
            "Abstract; Section 3, Proposed MuSACo Approach, especially "
            "source-subject selection and target pseudo-label co-training; "
            "Section 4.1, experimental protocol."
        ),
    }]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_id": "S227",
        "status": "author_preprint_method_located",
        "version": "arXiv:2508.12522v2",
        "boundary": (
            "The author preprint and WACV proceedings describe the same work. "
            "Expression recognition on BioVid, StressID, and BAH is not "
            "external clinical pain or SCS validation."
        ),
    }
    snapshot = snapshot_repository(DATA, label="pre-s227-claim-locator")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "s227-claim-locator-review-2026-09-25.json", audit)
    print(f"Updated S227 claim locator; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
