"""Pin the Infinite Sugar artwork description to an immutable README."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
URL = (
    "https://github.com/cnqso/infinite-sugar/blob/"
    "fdbbd866b203a709a164970b0a8996108edd57a5/README.md"
)


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    rows = [
        row for row in matrix["rows"]
        if row["source_ids"] == ["S201"]
        and row["locators"][0]["locator"] == "validated evidence row"
    ]
    if len(rows) != 1:
        raise ValueError("Expected one generic S201 row")
    rows[0]["locators"] = [{
        "source_id": "S201",
        "url": URL,
        "locator": (
            "Pinned README, project description, Run locally and Controls: "
            "browser artwork with simulated fly and inspectable activity."
        ),
    }]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_id": "S201",
        "pinned_commit": "fdbbd866b203a709a164970b0a8996108edd57a5",
        "status": "pinned_readme_located",
        "boundary": (
            "The README is the author's software description; the artwork "
            "does not independently validate neural or pain-related biology."
        ),
    }
    snapshot = snapshot_repository(DATA, label="pre-s201-claim-locator")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "s201-claim-locator-review-2026-09-25.json", audit)
    print(f"Updated S201 claim locator; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
