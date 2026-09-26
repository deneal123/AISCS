"""Integrate the Sapkal 2026 experimental walking comparator into SRC-03."""

# ruff: noqa: E501 -- retain precise section and figure locators.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
PRIMARY = "https://www.biorxiv.org/content/10.64898/2026.04.29.721658v2.full"


def field(state: str, value: str | None, locator: str, reason: str) -> dict:
    return {
        "state": state,
        "value": value,
        "reason": reason,
        "checked_at": DATE,
        "locators": [{"url": PRIMARY, "locator": locator}],
    }


def update() -> tuple[dict, dict]:
    audit = json.loads((DATA / "drosophila-connectome-audit.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    if any(item["source_id"] == "S763" for item in audit["entries"]):
        raise ValueError("S763 already audited")
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-01")
    if "S763" in stream["source_ids"]:
        raise ValueError("S763 already in NS-01")

    audit["entries"].append({
        "source_id": "S763",
        "extraction": {
            "connectome_version": field(
                "reported",
                "MANC v1.2.3; MaleCNS v0.9; BANC v626 for connectome-guided motif search",
                "Methods > Connectome analysis > Finding putative CPG-motif, first paragraph",
                "These are versions explicitly used in Sapkal et al.; they do not establish the source versions of S740's separately processed matrices.",
            ),
            "organism_sex_stage": field(
                "reported",
                "Drosophila melanogaster adults; experiments mainly male, with specified female FeCO-silencing assay; MANC/MaleCNS male and BANC female reference connectomes",
                "Methods > Fly husbandry and experimental genotypes; Methods > FeCO silencing; Methods > Connectome analysis",
                "Sex and stage are stated in the primary methods; experimental flies and reference connectome specimens are distinguished.",
            ),
            "dynamic_model": field(
                "not_applicable",
                None,
                "Results > Kinematics-guided connectome search; Methods > Connectome analysis",
                "This paper ranks and traces anatomical candidate motifs against fly behavior; it does not simulate a connectome-constrained dynamical network.",
            ),
            "experimental_comparator": field(
                "reported",
                "Optogenetically evoked leg stepping in sensory-deprived, including decapitated and deafferented, adult flies; kinematics guide and constrain candidate CPG-motif selection",
                "Figure 1 and legend; Results > Kinematics-guided connectome search; Discussion > Empirical evidence for walking CPG in Drosophila",
                "Real fly behavior supports a walking-circuit hypothesis; it is not a preregistered or matrix-matched validation of S740's simulation.",
            ),
            "scope_boundary": field(
                "reported",
                "Adult fly walking motor circuitry only; no nociception, subjective pain, human ECAP or SCS outcome",
                "Abstract; Results > Kinematics-guided connectome search; Discussion",
                "Motor behavior and human therapeutic response are different constructs.",
            ),
        },
        "relationship_to_s740": {
            "source_id": "S740",
            "status": "related_nonindependent_candidate_comparison",
            "reason": "Discussion compares overlapping and distinct candidate neurons with Pugliese et al.; Acknowledgments say that Pugliese modeling results were shared before publication. Neither text maps Sapkal's MANC/MaleCNS/BANC versions to all four S740 input matrices.",
            "locators": [
                {"url": PRIMARY, "locator": "Discussion, paragraph comparing CPG candidates with Pugliese et al."},
                {"url": PRIMARY, "locator": "Acknowledgments, Tuthill and Brunton shared CPG modeling results before publication"},
            ],
        },
        "primary_version": "bioRxiv v2, posted 2026-05-05",
    })
    audit["entries"].sort(key=lambda item: item["source_id"])
    audit["meta"]["records_count"] = len(audit["entries"])
    stream["source_ids"].append("S763")
    stream["source_ids"].sort()
    return audit, protocol


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit, protocol = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-sapkal-connectome-review")
        atomic_write_json(DATA / "drosophila-connectome-audit.json", audit)
        atomic_write_json(DATA / "search-protocol.json", protocol)
        print(f"Applied S763 connectome review; snapshot: {snapshot}")
    else:
        print("Dry run: S763 adds experimental walking and version-pinned motif search to SRC-03")


if __name__ == "__main__":
    main()
