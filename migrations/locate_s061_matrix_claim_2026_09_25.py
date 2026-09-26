"""Pin the larval circuit stability claim to eLife Figure 7."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    rows = [
        row for row in matrix["rows"]
        if row["source_ids"] == ["S061"]
        and row["locators"][0]["locator"] == "validated evidence row"
    ]
    if len(rows) != 1:
        raise ValueError("Expected one generic S061 row")
    rows[0]["locators"] = [{
        "source_id": "S061",
        "url": "https://doi.org/10.7554/eLife.108643.1",
        "locator": (
            "Results, Maintenance of synaptic density and relative "
            "connectivity support functional stability across development; "
            "Figure 7B-E; Methods, Biophysical steady-state models."
        ),
    }]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_id": "S061",
        "status": "primary_figure_located",
        "boundary": (
            "EM-based structural comparison and passive single-cell model "
            "responses are not direct developmental neural recordings, "
            "whole-brain dynamics or subjective pain measurements."
        ),
    }
    snapshot = snapshot_repository(DATA, label="pre-s061-claim-locator")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "s061-claim-locator-review-2026-09-25.json", audit)
    print(f"Updated S061 claim locator; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
