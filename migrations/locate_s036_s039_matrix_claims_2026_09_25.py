"""Replace two imported evidence locators with precise publisher abstract locators."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
LOCATORS = {
    "S036": (
        "https://www.sciencedirect.com/science/article/pii/S0925231225027389",
        "Publisher abstract, Results: PainFusion+ achieves 35.40% accuracy "
        "on BioVid multimodal pain estimation.",
    ),
    "S039": (
        "https://www.sciencedirect.com/science/article/abs/pii/S174680942601815X",
        "Publisher abstract, Results: 87.68% ± 0.41% participant-level "
        "six-class accuracy across four subject-independent outer folds.",
    ),
}


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    for source_id, (url, locator) in LOCATORS.items():
        rows = [
            row for row in matrix["rows"]
            if row["source_ids"] == [source_id]
            and row["locators"][0]["locator"] == "validated evidence row"
        ]
        if len(rows) != 1:
            raise ValueError(f"Expected one generic evidence row for {source_id}")
        rows[0]["locators"] = [{"source_id": source_id, "url": url, "locator": locator}]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_ids": list(LOCATORS),
        "status": "two_primary_abstract_locators_reviewed",
        "boundary": "Publisher abstracts support the stated metrics only. "
        "They do not establish independent clinical validation or an "
        "unreported split unit for S036.",
    }
    snapshot = snapshot_repository(DATA, label="pre-s036-s039-evidence-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "s036-s039-evidence-locator-review-2026-09-25.json", audit)
    print(f"Updated two abstract locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
