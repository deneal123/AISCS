"""Pin olfactory hardware and Eon self-description claims to source sections."""

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
LOCATORS = {
    "S214": (
        "https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2024.1384336/full",
        "Sections 2.1 and 2.5, hemibrain v1.2.1 olfactory topology "
        "and FPGA implementation; Results 3.4 and Figure 8, real-time "
        "hardware execution.",
    ),
    "S253": (
        "https://eon.systems/updates/embodied-brain-emulation",
        "Author project update, Model and sensory-body integration; "
        "NeuroMechFly and MuJoCo paragraphs; four-part sensorimotor loop.",
    ),
    "S296": (
        "https://eon.systems/updates/first-multi-behavior-brain-upload",
        "Author project update, final mission paragraphs: planned mouse "
        "connectome and functional recording programme.",
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
        "status": "primary_sections_located",
        "boundary": (
            "S214 is a restricted olfactory SNN and FPGA demonstration. "
            "S253 and S296 are first-party project descriptions; they do not "
            "independently validate whole-brain behavioral fidelity, future "
            "mouse emulation, nociception or human transfer."
        ),
    }
    snapshot = snapshot_repository(DATA, label="pre-three-olfactory-eon-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "three-olfactory-eon-locator-review-2026-09-25.json", audit)
    print(f"Updated three evidence locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
