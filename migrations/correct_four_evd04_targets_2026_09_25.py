"""Correct four evidence-matrix target constructs found in EVD-04 review."""

# ruff: noqa: E501 -- keep source-specific construct wording intact.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MATRIX = DATA / "evidence-matrix.json"
AUDIT = DATA / "four-construct-target-corrections-2026-09-25.json"
CORRECTIONS = {
    "S149": {
        "old": "pain intensity",
        "new": "Dataset-specific UNBC pain regression, BioVid four-class heat-stimulus recognition and neonatal binary pain/no-pain classification (separate N-PASS subset); no common endpoint",
        "url": "https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.1827727/full",
        "locator": "Methods > 4.3 neonatal annotations; Results > Tables 9-11; Section 5.2.3",
        "reason": "The three benchmark tasks use different labels, scales and populations and must not be represented by one pain-intensity metric.",
    },
    "S023": {
        "old": "clinical_function",
        "new": "Future central neuropathic-pain development within six months after subacute spinal-cord injury (PDP versus PNP)",
        "url": "https://eprints.gla.ac.uk/345351/",
        "locator": "Published-version abstract, Methods: datasets A/B and PDP versus PNP within six months",
        "reason": "The classifier target is later neuropathic-pain status, not a measure of clinical function or momentary pain intensity.",
    },
    "S154": {
        "old": "nociceptive_response",
        "new": "Nociceptor ribosome-bound RNA abundance after larval UV injury versus sham (translatomic assay)",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12377072/",
        "locator": "Methods > Translating Ribosome Affinity Purification and RNA sequencing; Data Records",
        "reason": "The source is an injury/sham molecular dataset, not a direct neural-activity or protective-behavior measurement.",
    },
    "S253": {
        "old": "protective_behavior",
        "new": "Engineered virtual-fly sensorimotor behavior: food navigation, feeding and grooming",
        "url": "https://eon.systems/updates/embodied-brain-emulation",
        "locator": "How does the fly work?; Behaviors; What the current embodied fly is not",
        "reason": "The demonstrated behaviors are engineered feeding, grooming and navigation; escape was not implemented in the body model.",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    review = []
    for source_id, correction in CORRECTIONS.items():
        rows = [
            row for row in matrix["rows"]
            if row["source_ids"] == [source_id] and row["target_variable"] == correction["old"]
        ]
        assert len(rows) == 1, source_id
        row = rows[0]
        assert row["target_variable"] == correction["old"], source_id
        row["target_variable"] = correction["new"]
        review.append({
            "source_id": source_id,
            "batch_id": row["batch_id"],
            "old_target": correction["old"],
            "corrected_target": correction["new"],
            "reason": correction["reason"],
            "primary_locator": {"url": correction["url"], "locator": correction["locator"]},
        })
    if not args.apply:
        print("Dry run: four construct targets corrected")
        return
    snapshot = snapshot_repository(DATA, label="pre-four-construct-target-corrections")
    atomic_write_json(MATRIX, matrix)
    atomic_write_json(AUDIT, {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25", "gate": "G0_REVISE", "scope": "EVD-04 target-variable corrections in existing evidence rows"},
        "corrections": review,
        "boundary": "These corrections align construct labels with primary reports; they do not complete source-card review, EVD-03 or author acceptance.",
    })
    print(f"Corrected four matrix targets; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
