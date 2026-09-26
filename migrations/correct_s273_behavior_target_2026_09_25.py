"""Separate the S273 mouse behavioral endpoint from neural-response labels."""

# ruff: noqa: E501 -- retain exact experimental and clinical boundaries.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MATRIX = DATA / "evidence-matrix.json"
AUDIT = DATA / "s273-behavior-target-correction-2026-09-25.json"
SOURCE_URL = "https://advanced.onlinelibrary.wiley.com/doi/abs/10.1002/adsu.70449"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    rows = [row for row in matrix["rows"] if row["source_ids"] == ["S273"]]
    assert len(rows) == 1
    row = rows[0]
    assert row["target_variable"] == "nociceptive_response"
    row.update({
        "claim": "The MenstruEase paper describes an sEMG/EDA-triggered TENS prototype and reports longer hot-plate paw-withdrawal latency in female mice under TENS-equivalent stimulation.",
        "target_variable": "Mouse hot-plate paw-withdrawal latency (protective behavior); separately, sEMG/EDA controller inputs",
        "verified_evidence": "Publisher abstract reports paw-withdrawal latency rising from 7.3 +/- 0.2 seconds to about 10.7 seconds (p=0.012) in a female-mouse proof of concept.",
        "limitations": "Animal behavioral endpoint only; no direct nociceptor recording, human dysmenorrhea outcome, or validated AI pain detector. AI detection and adaptive dose selection are described as a roadmap.",
        "permitted_conclusion": "Use as a mouse behavioral and TENS-controller prototype precedent; do not infer subjective pain intensity or clinical efficacy for women.",
        "locators": [{"source_id": "S273", "url": SOURCE_URL, "locator": "Publisher abstract: sEMG/EDA controller, female-mouse hot-plate paw-withdrawal latency and future AI roadmap"}],
    })
    if not args.apply:
        print("Dry run: S273 behavioral target corrected")
        return
    snapshot = snapshot_repository(DATA, label="pre-s273-behavior-target-correction")
    atomic_write_json(MATRIX, matrix)
    atomic_write_json(AUDIT, {
        "meta": {"schema_version": "1.0.0", "checked_at": "2026-09-25", "gate": "G0_REVISE"},
        "source_id": "S273",
        "old_target": "nociceptive_response",
        "corrected_target": row["target_variable"],
        "primary_locator": {"url": SOURCE_URL, "locator": "Publisher abstract, proof-of-concept mouse hot-plate result"},
        "boundary": "Paw withdrawal is a protective behavior and cannot establish human pain relief or a neural recording.",
    })
    print(f"Corrected S273 matrix row; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
