"""Link two Drosophila nociception claims to primary text sections."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
LOCATORS = {
    "S065": (
        "https://elifesciences.org/reviewed-preprints/110557",
        "Reviewed preprint Abstract and Discussion: Kir2.1 silencing of PPL1/PAM "
        "dopaminergic neurons and MBON silencing alter adult escape latency.",
    ),
    "S212": (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PPR1092389/fullTextXML",
        "JATS Abstract and Results §S25-28: brain-wide imaging followed by "
        "eFIB-SEM of the same first-instar CNS; 119 responsive neurons across 25 lineages.",
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
            raise ValueError(f"Expected one generic row for {source_id}")
        rows[0]["locators"] = [{"source_id": source_id, "url": url, "locator": locator}]
        if source_id == "S065":
            rows[0]["limitations"] += (
                " The eLife assessment rates the evidence incomplete, "
                "so the proposed circuit should not be treated as fully established."
            )
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_ids": list(LOCATORS),
        "status": "two_nociception_locators_reviewed",
        "boundary": "S065 is an adult behavioral circuit proposal with an incomplete "
        "eLife evidence assessment. S212 imaging/EM and separate behavior cohorts "
        "are distinct. Neither measures subjective pain.",
    }
    snapshot = snapshot_repository(DATA, label="pre-s065-s212-evidence-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "s065-s212-evidence-locator-review-2026-09-25.json", audit)
    print(f"Updated two nociception locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
