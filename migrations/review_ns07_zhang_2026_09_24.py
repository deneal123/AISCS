"""Add Zhang's primary ECAP simulation to the open NS-07/NS-09 audits."""

# ruff: noqa: E501 -- precise source locators and model boundaries are required.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC9927682/"


def field(value: str | None, locator: str, *, state: str = "reported") -> dict:
    return {
        "state": state,
        "value": value,
        "reason": "Checked in the primary Chinese journal text and English abstract; model output is not clinical validation.",
        "checked_at": DATE,
        "locators": [{"url": URL, "locator": locator}],
    }


def update() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "ecap-scs-audit.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    if not any(item["id"] == "S768" for item in records["sources"]):
        raise ValueError("S768 must be published first")
    if any(item["source_id"] == "S768" for item in audit["entries"]):
        raise ValueError("S768 already audited")
    if any("S768" in row["source_ids"] for row in matrix["rows"]):
        raise ValueError("S768 already in evidence matrix")
    if any(item["id"] == "NS-RUN-2026-09-24-15" for item in protocol["search_runs"]):
        raise ValueError("Search run already exists")

    audit["entries"].append({
        "source_id": "S768",
        "extraction": {
            "sample": field(None, "section 1.1: MRI measurements from 15 volunteers belong to an earlier source study; current study simulates anatomy", state="not_applicable"),
            "electrode_geometry": field("T10-centered 3-D conductor, 26 superficial white-matter regions, eight-contact 1.3-mm lead; differential E8-E7 ECAP recording relative to E2 reference", "sections 1.1 and 1.3, Figures 1 and 3"),
            "stimulation": field("ANSYS conductor potentials drive NEURON multicompartment sensory fibers; 210-microsecond pulse; reciprocity projects membrane currents to single-fiber potentials summed into ECAP", "sections 1.1-1.4, Figures 1-4"),
            "split_unit": field(None, "sections 1-2: simulation without a patient-level split", state="not_applicable"),
            "metrics": field("Simulation: no more than 10% dorsal-column activation produced peaks from large fibers; at least 20% produced a slow-conduction peak from smaller fibers", "English Abstract; section 2 Results"),
        },
    })
    audit["meta"]["records_count"] = len(audit["entries"])
    review = audit["ns07_forward_model_review"]
    review["direct_model_sources"] = list(dict.fromkeys([*review["direct_model_sources"], "S768"]))
    review["decision"] = "S766 and S768 directly establish FEM/multicompartment/reciprocity ECAP forward modeling as prior art; S363 and S764 add adjacent models. S768's activation fractions are simulation outputs, not measured human recruitment or analgesic response. S105 remains empirical signal analysis."
    review["remaining"] = "Finish backward/forward primary citation screening for historical models and patent families, then perform a later dated refresh; NS-07 and PA-04 remain open."
    for stream_id in ("NS-07", "NS-09"):
        stream = next(item for item in protocol["search_streams"] if item["id"] == stream_id)
        if "S768" in stream["source_ids"]:
            raise ValueError(f"S768 already in {stream_id}")
        stream["source_ids"].append("S768")
    protocol["search_runs"].append({
        "id": "NS-RUN-2026-09-24-15",
        "date": DATE,
        "queries": [
            "Anaya 2019 forward citation spinal ECAP Zhang 2021 simulation",
            "10.7507/1001-5515.202007016 volume conductor multicompartment SFAP",
        ],
        "primary_urls": [URL, "https://pubmed.ncbi.nlm.nih.gov/33913282/"],
        "new_mechanism_classes": [],
        "direct_drosophila_ecap_scs_analogue_found": False,
        "saturation": False,
    })
    matrix["rows"].append({
        "batch_id": "ns07-zhang-primary-review-2026-09-24",
        "claim": "Simulated ECAP waveform decomposition by dorsal-column fiber recruitment is established prior art.",
        "target_variable": "Simulated ECAP differential waveform and activated fiber fraction",
        "population_or_data": "Human-anatomy-based computational T10 model; no enrolled clinical ECAP cohort",
        "source_ids": ["S768"],
        "verified_evidence": "Sections 1.1-1.4 combine ANSYS conductor fields, NEURON fibers and reciprocity-based SFAP summation; the abstract and Results compare simulated peaks under different activation fractions.",
        "limitations": "No independent clinical waveform or patient-level pain-outcome validation; source MRI cohort supplies geometry only.",
        "permitted_conclusion": "Use as direct ECAP observation and recruitment-estimation model prior art, not as validated clinical prediction.",
        "locators": [{"source_id": "S768", "url": URL, "locator": "English Abstract; sections 1.1-1.4 and 2, Figures 1-4"}],
    })
    return audit, protocol, matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    audit, protocol, matrix = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns07-zhang-primary-review")
        atomic_write_json(DATA / "ecap-scs-audit.json", audit)
        atomic_write_json(DATA / "search-protocol.json", protocol)
        atomic_write_json(DATA / "evidence-matrix.json", matrix)
        print(f"Applied S768 NS-07/09 review; snapshot: {snapshot}")
    else:
        print("Dry run: S768 is ready for NS-07/09; PA-04 remains open")


if __name__ == "__main__":
    main()
