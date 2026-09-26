"""Clarify the ECAP and patient-outcome boundaries in three PA-04 rows."""

# ruff: noqa: E501 -- keep evidence statements intact for source comparison.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MATRIX = DATA / "evidence-matrix.json"

REVISIONS = {
    "S784": {
        "claim": "Human spinal ECAP recordings show A-beta recruitment during SCS and an association with spatial coverage of the painful area.",
        "target_variable": "ECAP threshold and growth (neural recruitment); separately, spatial coverage of the painful area",
        "verified_evidence": "A-beta responses appear above a stimulation threshold and increase with current; amplitude correlates with painful-area coverage.",
        "permitted_conclusion": "ECAP tracks evoked neural recruitment and is associated with painful-area coverage in this report; ECAP does not measure pain intensity or relief.",
    },
    "S787": {
        "claim": "ECAP threshold covaries with perception and discomfort thresholds during SCS programming in 14 participants.",
        "target_variable": "ECAP threshold (neural); perception and discomfort thresholds (participant-reported sensory endpoints)",
        "verified_evidence": "Across repeated growth curves, ECAP threshold correlated with perception threshold (r=0.93, n=112 curves) and discomfort threshold (r=0.93, n=108 curves).",
        "permitted_conclusion": "Supports a programming-threshold association in 14 participants; it does not validate analgesic-response prediction or ECAP as a direct pain measure.",
    },
    "S788": {
        "claim": "The preliminary AVALON report describes patient-reported pain and function after closed-loop SCS implantation.",
        "verified_evidence": "Of 51 trialed participants, 36 received implants; pain, quality-of-life, function and sleep outcomes were reported at three and six months.",
        "permitted_conclusion": "Describes outcomes after treatment in one selected cohort; it cannot isolate the effect of ECAP feedback, estimate a comparative treatment effect or validate individual prognosis.",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    selected = {
        r["source_ids"][0]: r
        for r in matrix["rows"]
        if len(r["source_ids"]) == 1 and r["source_ids"][0] in REVISIONS
    }
    assert set(selected) == set(REVISIONS)
    for source_id, fields in REVISIONS.items():
        selected[source_id].update(fields)
    if not args.apply:
        print("Dry run: clarified PA-04 evidence rows S784, S787 and S788")
        return
    snapshot = snapshot_repository(DATA, label="pre-pa04-matrix-boundary-clarification")
    atomic_write_json(MATRIX, matrix)
    print(f"Updated three PA-04 matrix rows; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
