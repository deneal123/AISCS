"""Pin five code-only evidence claims to immutable repository files."""
# ruff: noqa: E501 -- immutable GitHub URLs are intentionally exact.

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
LOCATORS = {
    "S292": (
        "https://github.com/legacyindiesubmissions-ai/claude-fly/blob/3a035275148e97539711728422548bffe2a77566/README.md",
        "Pinned README, Paper and Abstract: companion of S320, FlyWire v783 "
        "and two simulated agents; no independent replication.",
    ),
    "S732": (
        "https://github.com/eonsystemspbc/fly-brain/blob/a3db62f9436074e485c0278290c2164ed6150808/README.md",
        "Pinned README, Quickstart, Project structure and Data: Brian2, "
        "PyTorch and NEST GPU LIF backends, benchmark runner, FlyWire v783.",
    ),
    "S733": (
        "https://github.com/Neuromorphicism/fly-brain-snntorch/blob/fe55fb0cff275a2b6b54926524c8d831838e32fc/README.md",
        "Pinned README, Sensory Experiments and Results: snnTorch port, "
        "four engineered sensory inputs, dense/sparse implementations.",
    ),
    "S734": (
        "https://github.com/NeLy-EPFL/flygym/blob/38c8ec61034cd59bc5ba0de20688d4a3c0000d60/README.md",
        "Pinned README, NeuroMechFly v2 introduction and components: "
        "adult-fly embodied sensorimotor simulation framework.",
    ),
    "S737": (
        "https://github.com/gauravvvvvvvvvv/flybox/blob/5880d221e21b1f3385b7246a6ffc3b2cf0029c2c/docs/BROWSER_RUNTIME.md",
        "Pinned browser-runtime guide: FlyBrain graph export, browser-only "
        "simulation and experimental sensory/motor mappings.",
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
            raise ValueError(f"Expected one generic code row for {source_id}")
        rows[0]["locators"] = [{"source_id": source_id, "url": url, "locator": locator}]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25"},
        "source_ids": list(LOCATORS),
        "status": "five_pinned_code_locators_reviewed",
        "boundary": "Repository descriptions are software-source evidence. "
        "They do not establish biological fidelity, subjective pain, "
        "human ECAP or SCS efficacy; S292 is companion code to S320.",
    }
    snapshot = snapshot_repository(DATA, label="pre-five-code-claim-locators")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "five-code-claim-locator-review-2026-09-25.json", audit)
    print(f"Updated five pinned code locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
