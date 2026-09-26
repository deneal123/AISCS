"""Pin three fly evidence claims to their primary result sections."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
LOCATORS = {
    "S154": (
        "https://www.mdpi.com/2306-5729/10/2/11",
        "Abstract; Sections 2.1 and 3.3; Data Availability Statement, "
        "BioProject PRJNA1056042: UV-injured versus sham larval "
        "class-IV nociceptor ribosome-bound RNA sequencing.",
    ),
    "S068": (
        "https://www.nature.com/articles/s41586-024-07982-0",
        "Abstract; Main, connectome-prior estimator; Fig. 3 and simulation "
        "Methods: estimation efficiency shown in connectome-based simulations.",
    ),
    "S286": (
        "https://arxiv.org/html/2602.17997v3",
        "Sections 3.1-3.2 and 4.1-4.3; Table 1: connectome graph "
        "policy and simulated flybody locomotion comparisons.",
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
        if source_id == "S068":
            rows[0]["claim"] = (
                "The study proposes using the fly connectome as a prior for "
                "causal effectome estimation and demonstrates improved "
                "estimation efficiency in connectome-based simulations."
            )
        elif source_id == "S286":
            rows[0]["target_variable"] = "not_applicable"

    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_ids": list(LOCATORS),
        "status": "primary_sections_located",
        "boundary": (
            "S154 is molecular translatomic data, not an evoked neural or "
            "behavioral outcome. S068 validates its estimator in simulation, "
            "not a whole-brain biological perturbation dataset. S286 tests "
            "simulated locomotion, not protective behavior or nociception."
        ),
    }
    snapshot = snapshot_repository(DATA, label="pre-three-fly-claim-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "three-fly-claim-locator-review-2026-09-25.json", audit)
    print(f"Updated three fly claim locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
