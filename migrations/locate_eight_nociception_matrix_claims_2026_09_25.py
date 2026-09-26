"""Reuse reviewed primary locators for eight nociception evidence rows."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
SOURCE_FIELDS = {
    "S027": ("stimulus", "behavior"),
    "S066": ("neural_response", "behavior"),
    "S092": ("stimulus", "neural_response", "behavior"),
    "S030": ("neural_response", "behavior"),
    "S029": ("neural_response", "behavior"),
    "S012": ("stimulus", "pain_boundary"),
    "S152": ("stimulus", "pain_boundary"),
    "S282": ("neural_response", "behavior"),
}


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    source_audit = json.loads(
        (DATA / "drosophila-nociception-audit.json").read_text(encoding="utf-8")
    )
    entries = {entry["source_id"]: entry for entry in source_audit["entries"]}
    for source_id, fields in SOURCE_FIELDS.items():
        rows = [
            row for row in matrix["rows"]
            if row["source_ids"] == [source_id]
            and row["locators"][0]["locator"] == "validated evidence row"
        ]
        if len(rows) != 1:
            raise ValueError(f"Expected one generic evidence row for {source_id}")
        locators = []
        for field in fields:
            for locator in entries[source_id]["extraction"][field]["locators"]:
                item = {"source_id": source_id, **locator}
                if item not in locators:
                    locators.append(item)
        rows[0]["locators"] = locators

    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_ids": list(SOURCE_FIELDS),
        "status": "primary_locators_reused_from_reviewed_nociception_audit",
        "locator_source": "data/drosophila-nociception-audit.json",
        "boundary": (
            "The locators support the respective reported assays or review scope. "
            "Neural activity, defensive behavior, and subjective pain are distinct; "
            "S012 and S152 are reviews, and S282 imaging and behavior cohorts differ."
        ),
    }
    snapshot = snapshot_repository(DATA, label="pre-eight-nociception-claim-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "eight-nociception-claim-locator-review-2026-09-25.json", audit)
    print(f"Updated eight nociception locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
