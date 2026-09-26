"""Remove rejected identity candidates from the positive evidence matrix."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
REJECTED = {"S140", "S361", "S011"}
OLD_NOTE = (
    "No matching pain/SCS source was found; the exact-title Crossref "
    "hit was an unrelated crystal-growth article."
)
NEW_NOTE = (
    "No primary record matching the imported pain-detection-from-SCS-data "
    "title was established. The highest-ranked candidate from a broad "
    "Crossref title query is an unrelated crystal-growth article, not an "
    "exact-title match."
)


def main() -> None:
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    rows = [row for row in matrix["rows"] if set(row["source_ids"]) & REJECTED]
    if len(rows) != 3 or {row["source_ids"][0] for row in rows} != REJECTED:
        raise ValueError("Unexpected rejected identity evidence rows")
    if any(row["permitted_conclusion"] != "Do not cite as evidence." for row in rows):
        raise ValueError("A rejected identity row may have been promoted")
    matrix["rows"] = [
        row for row in matrix["rows"] if not set(row["source_ids"]) & REJECTED
    ]

    source = next(item for item in records["sources"] if item["id"] == "S011")
    if source["validation"]["notes"] != OLD_NOTE:
        raise ValueError("S011 note has changed")
    source["validation"]["notes"] = NEW_NOTE
    for resolution in source["field_resolution"].values():
        if resolution.get("value") == OLD_NOTE:
            resolution["value"] = NEW_NOTE

    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "removed_source_ids": sorted(REJECTED),
        "reason": (
            "These rejected candidates have no uniquely identified primary "
            "record and explicitly forbid citation as evidence. The evidence "
            "matrix must not assert positive primary traceability for them."
        ),
        "source_records_retained": True,
        "s011_note_correction": "Broad Crossref query was not an exact-title match.",
        "verification_boundary": (
            "Negative registry searches are dated search observations, not "
            "proof that a source can never exist. A 2026-09-25 Google Patents "
            "request returned HTTP 503 and cannot strengthen S140's status."
        ),
    }
    snapshot = snapshot_repository(DATA, label="pre-unverified-evidence-row-removal")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "three-unverified-row-removal-2026-09-25.json", audit)
    print(f"Removed three rejected identity rows; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
