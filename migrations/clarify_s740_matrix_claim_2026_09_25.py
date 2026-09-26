"""Pin the S740 matrix claim to its simulation and optogenetic result sections."""

# ruff: noqa: E501 -- primary-locator wording is intentionally explicit.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MATRIX = DATA / "evidence-matrix.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    matches = [row for row in matrix["rows"] if row["source_ids"] == ["S740"]]
    assert len(matches) == 1
    row = matches[0]
    assert row["claim"] == "Dynamic VNC connectome simulation can nominate a compact motor circuit and a pathway validated optogenetically."
    row.update({
        "claim": "Dynamic VNC connectome simulations nominate a compact walking-rhythm circuit; DNb08 activation evokes rhythmic leg movements in decapitated flies.",
        "verified_evidence": "Four VNC connectome simulations nominate an E-E-I rhythm-generating circuit; optogenetic DNb08 activation evokes rhythmic leg movements resembling searching, not coordinated walking.",
        "limitations": "The optogenetic assay tests a nominated fly motor pathway, not the exact four upstream matrix releases, nociception, subjective pain, human ECAP or SCS.",
        "permitted_conclusion": "Use as a connectome-simulation and fly motor-perturbation precedent; the biological comparison is limited to DNb08-evoked rhythmic leg movement.",
        "locators": [{
            "source_id": "S740",
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13142387/",
            "locator": "Methods > VNC connectome datasets; Results > DNb08 optogenetic activation and Fig. 5c-e; see also PubMed PMID 42094485, abstract and Fig. 5 legend",
        }],
    })
    if not args.apply:
        print("Dry run: S740 claim and primary locators clarified")
        return
    snapshot = snapshot_repository(DATA, label="pre-s740-matrix-claim-clarification")
    atomic_write_json(MATRIX, matrix)
    print(f"Updated S740 matrix claim; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
