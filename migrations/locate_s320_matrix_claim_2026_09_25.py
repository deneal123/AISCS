"""Link S320 evidence claim to its previously checked author PDF."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
URL = "https://zenodo.org/api/records/19152238/files/paper_emergent_individuality.pdf/content"


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    rows = [
        row for row in matrix["rows"]
        if row["source_ids"] == ["S320"]
        and row["locators"][0]["locator"] == "validated evidence row"
    ]
    if len(rows) != 1:
        raise ValueError("Expected one generic S320 row")
    rows[0]["locators"] = [
        {
            "source_id": "S320",
            "url": URL,
            "locator": "Author PDF pp. 1-3, Abstract and Methods 2.1-2.5: "
            "FlyWire v783, LIF simulation, plasticity and MuJoCo sensorimotor loop.",
        },
        {
            "source_id": "S320",
            "url": URL,
            "locator": "Author PDF pp. 3-10, Results and Limitations: "
            "two simulated agents diverge; no matched biological comparator.",
        },
    ]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_id": "S320",
        "status": "primary_pdf_locator_reused",
        "primary_pdf_sha256": "3C3FDEC049B5D9E811FC99E7942542B22A55634274B38C1E1066EABDEF3607C2",
        "boundary": "The PDF was checked in the existing connectome audit; "
        "the results are author-reported and were not independently reproduced.",
    }
    snapshot = snapshot_repository(DATA, label="pre-s320-evidence-locator")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "s320-evidence-locator-review-2026-09-25.json", audit)
    print(f"Updated S320 locator; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
